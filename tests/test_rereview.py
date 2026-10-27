"""Regressions for required research inputs and exposure after verified closure."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from aced import ApprovalStatus, Goal, Step, VerificationStatus
from aced.reference import demo_project
from aced.workflow import timestamp
from tests.test_review_corrections import active_main, settle_failure
from tests.test_runtime import compose, drive


@pytest.mark.parametrize("identity", ["same", "different"])
@pytest.mark.parametrize("held", [False, True])
async def test_healthy_positive_exposure_after_settlement_stops_before_decide(
    tmp_path, identity, held
):
    path = tmp_path / "fresh-rereview.sqlite3"
    runtime, clock, runner, infra, principal = compose(path)
    infra.continue_cycles = 1
    view = await active_main(runtime, clock)
    settled = await settle_failure(runtime, clock, infra, view.id)
    old_stop = settled.data["stop_request_id"]
    old_history = await runtime.history(view.id)
    old_starts = tuple(runner.starts)
    if held:
        await runtime.hold(view.id)
    safety, read, authorize = infra.safety, infra.read_evidence, infra.authorize
    reports = []

    async def reexposed(*args):
        report = replace(
            await safety(*args),
            healthy=True,
            stop_required=False,
            exposure_active=True,
            zero_confirmed=False,
            experiment_id=settled.data["experiment_id"] if identity == "same" else "other-main",
            candidate=settled.data["candidate"],
            plan_fingerprint=settled.data["plan_fingerprint"],
        )
        reports.append(report)
        return report

    async def pending_settlement(request, principal):
        value = await read(request, principal)
        if request.task.purpose == "reconcile":
            return replace(value, status=VerificationStatus.WAITING, facts={})
        return value

    async def review_cleanup(task, principal, **kwargs):
        value = await authorize(task, principal, **kwargs)
        return (
            replace(value, status=ApprovalStatus.WAITING) if task.purpose == "reconcile" else value
        )

    infra.safety, infra.read_evidence, infra.authorize = (
        reexposed,
        pending_settlement,
        review_cleanup,
    )
    stopping = await runtime.advance(view.id)
    assert reports and reports[-1].healthy and reports[-1].exposure_active
    assert stopping.status == "stopping"
    assert stopping.data["stop_request_id"] != old_stop
    assert stopping.data["settled_stop_request_id"] == old_stop
    assert not stopping.data["cleanup_confirmed"]
    assert not stopping.data["effects_settled"] and not stopping.data["experiment_zero"]
    assert "exposure" in stopping.data["stop_reason"]
    assert tuple(runner.starts) == old_starts
    assert len(set(infra.stop_requests)) == 2
    assert (await runtime.history(view.id))[: len(old_history)] == old_history
    new_stop = stopping.data["stop_request_id"]
    await runtime.close()
    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=principal)
    for _ in range(3):
        clock.tick()
        pending = await runtime.advance(view.id)
        assert pending.status == "stopping" and pending.data["stop_request_id"] == new_stop
    assert tuple(runner.starts) == old_starts and len(set(infra.stop_requests)) == 2
    infra.safety, infra.read_evidence, infra.authorize = safety, read, authorize
    for _ in range(8):
        clock.tick()
        recovered = await runtime.advance(view.id)
        if recovered.data.get("cleanup_confirmed"):
            break
    assert recovered.step is Step.DECIDE and recovered.data["experiment_zero"]
    if held:
        assert recovered.status == "held"
        await runtime.resume(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and len(set(infra.stop_requests)) == 2
    assert await runtime.store.verify_audit()
    await runtime.close()


async def test_legitimate_healthy_active_main_does_not_trigger_new_stop():
    runtime, clock, _, infra, _ = compose()
    infra.continue_cycles = 1
    view = await active_main(runtime, clock)
    assert any(not item["zero"] for item in infra.exposures.values())
    active = await runtime.advance(view.id)
    assert active.status == "active" and active.step is Step.EXPERIMENT
    assert not infra.stop_requests
    assert (await drive(runtime, clock, view.id)).status == "completed"
    await runtime.close()


@pytest.mark.parametrize("phase", ["readout", "stale_readout", "proposal", "promotion", "rollback"])
async def test_positive_exposure_after_main_zero_requires_actual_disposition_authority(phase):
    config = demo_project(Path("/tmp/product"))
    config = replace(config, plan=replace(config.plan, readout_delay_seconds=20))
    runtime, clock, runner, infra, _ = compose(config=config)
    infra.continue_cycles = 1
    if phase == "rollback":
        infra.outcome = "revert"
        read = infra.read_evidence

        async def propose_rollback(request, principal):
            verdict = await read(request, principal)
            if request.task.scope == "decision":
                facts = dict(verdict.facts)
                facts.pop("learning", None)
                facts.update(
                    proposed_disposition="reverted", proposal_reference="fixture:rollback-review"
                )
                return replace(verdict, facts=facts)
            return verdict

        infra.read_evidence = propose_rollback
    view = await active_main(runtime, clock)
    clock.value = timestamp(view.data["experiment_deadline"])
    view = await runtime.advance(view.id)
    assert view.data["experiment_zero"] and view.step is Step.EXPERIMENT
    if phase in {"proposal", "promotion", "rollback"}:
        view = await drive(runtime, clock, view.id, target=Step.DECIDE, scope="disposition")
    if phase in {"promotion", "rollback"}:
        view = await runtime.advance(view.id)
        assert runner.tasks[view.data["current"]].scope == "disposition"
    observed = infra.safety

    async def active(*args):
        report = replace(
            await observed(*args),
            healthy=True,
            exposure_active=True,
            zero_confirmed=False,
            experiment_id=view.data["experiment_id"],
            candidate=view.data["candidate"],
            plan_fingerprint=view.data["plan_fingerprint"],
        )
        if phase == "stale_readout":
            deadline = timestamp(view.data["experiment_deadline"])
            report = replace(
                report,
                observed_at=deadline - timedelta(seconds=1),
                valid_until=deadline,
                exposure_end=deadline,
            )
        return report

    infra.safety = active
    next_view = await runtime.advance(view.id)
    if phase in {"readout", "proposal", "rollback"}:
        assert infra.stop_requests
        assert (
            next_view.data["stop_reason"] == "positive exposure observed after confirmed settlement"
        )
    else:
        assert not infra.stop_requests
        assert next_view.data["scope"] == (
            "disposition" if phase == "promotion" else "main_exposure"
        )
    await runtime.close()


async def test_required_research_observation_blocks_before_freeze_and_survives_restart(tmp_path):
    config = replace(demo_project(Path("/tmp/product")), require_research_observation=True)
    path = tmp_path / "fresh-observation.sqlite3"
    runtime, clock, runner, infra, principal = compose(path, config=config)
    view = await runtime.start(Goal("demo", "Scoped research"), key="required-input")
    waiting = await runtime.advance(view.id)
    assert waiting.data["current"] is None and not await runtime.tasks(view.id)
    assert "observation" in waiting.blocker and "before" in waiting.blocker
    assert waiting.data["reserved_tasks"] == waiting.data["task_count"] == 0
    for _ in range(3):
        clock.tick(10)
        assert (await runtime.advance(view.id)).revision == waiting.revision
    await runtime.close()
    runtime, *_ = compose(
        path,
        clock=clock,
        runner=runner,
        infra=infra,
        identity=principal,
        config=replace(config, require_research_observation=False),
    )
    assert (await runtime.advance(view.id)).data["current"] is None and not runner.starts
    await runtime.record_observation(view.id, "fixture:verified-overview")
    launched = await runtime.advance(view.id)
    task = runner.tasks[launched.data["current"]]
    assert task.context["observation_reference"] == "fixture:verified-overview"
    assert task.context["require_research_observation"] is True
    assert launched.data["reserved_tasks"] == 1 and len(runner.starts) == 1
    assert await runtime.store.verify_audit()
    await runtime.close()


async def test_next_hypothesis_requires_a_new_observation_without_losing_learning():
    config = replace(demo_project(Path("/tmp/product")), require_research_observation=True)
    runtime, clock, runner, _, _ = compose(config=config)
    view = await runtime.start(Goal("demo", "Learn twice"), key="fresh-cycle-input")
    await runtime.record_observation(view.id, "fixture:cycle-one")
    for _ in range(100):
        view = await runtime.advance(view.id)
        if view.cycle == 2:
            break
        if view.wake_at:
            clock.value = max(clock.value, timestamp(view.wake_at))
        clock.tick()
    assert view.step is Step.HYPOTHESIZE and "observation_reference" not in view.data
    assert view.data["learning"] and view.data["research_candidates"]
    count = len(runner.starts)
    blocked = await runtime.advance(view.id)
    assert "observation" in blocked.blocker and len(runner.starts) == count
    await runtime.record_observation(view.id, "fixture:cycle-two")
    await runtime.advance(view.id)
    task = runner.tasks[runner.starts[-1]]
    assert task.cycle == 2 and task.context["observation_reference"] == "fixture:cycle-two"
    assert task.context["learning"] and task.context["research_candidates"]
    await runtime.close()


def test_required_research_observation_is_a_boolean():
    with pytest.raises(TypeError, match="require_research_observation"):
        replace(demo_project(Path("/tmp/product")), require_research_observation="yes")


@pytest.mark.parametrize("reason", ["", "Capture a new scoped observation before launch"])
async def test_authority_wait_exposes_host_recovery_instructions_without_launch(reason):
    runtime, clock, runner, infra, _ = compose()
    authorize = infra.authorize

    async def needs_observation(task, principal, **kwargs):
        return replace(
            await authorize(task, principal, **kwargs),
            status=ApprovalStatus.WAITING,
            reason=reason,
        )

    infra.authorize = needs_observation
    view = await runtime.start(Goal("demo", "Research"), key="scope-wait")
    waiting = await runtime.advance(view.id)
    assert waiting.blocker == f"authorization waiting: {reason or 'fixture:authorization'}"
    assert waiting.data["task"]["authorization"]["reference"] == "fixture:authorization"
    for _ in range(3):
        clock.tick()
        assert (await runtime.advance(view.id)).revision == waiting.revision
    assert not runner.starts
    await runtime.close()
