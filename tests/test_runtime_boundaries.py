from dataclasses import replace
from datetime import timedelta

import pytest

from aced import (
    AgentResult,
    AgentStatus,
    ApprovalStatus,
    ConflictError,
    ExecutionRef,
    Goal,
    SafetyStatus,
    StaleLeaseError,
    Step,
    StopDelivery,
)
from aced.reference import envelope
from aced.runtime import _envelope
from aced.workflow import timestamp
from tests.test_runtime import compose, drive


async def new(runtime):
    return await runtime.start(Goal("demo", "Learn"), key="k")


async def unavailable(*args, **kwargs):
    raise OSError("sensitive host diagnostic must remain protected")


@pytest.mark.parametrize("operation", ["authorize", "read_evidence"])
async def test_host_exception_is_bounded_redacted_and_durable(operation):
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)
    if operation == "read_evidence":
        await runtime.advance(view.id)
    setattr(infra, operation, unavailable)
    blocked = await runtime.advance(view.id)
    assert "unavailable" in blocked.blocker and "OSError" in blocked.blocker
    assert "sensitive" not in blocked.blocker
    for _ in range(3):
        clock.tick(20)
        assert (await runtime.advance(view.id)).revision == blocked.revision
    assert len(runner.starts) <= 1
    await runtime.close()


async def test_authority_rechecked_after_completed_output():
    runtime, _, _, infra, _ = compose()
    view = await new(runtime)
    await runtime.advance(view.id)
    infra.approval = ApprovalStatus.DENIED
    assert "authority" in (await runtime.advance(view.id)).blocker
    assert (await runtime.inspect(view.id)).step == Step.HYPOTHESIZE
    infra.authorize = unavailable
    assert "authority unavailable" in (await runtime.advance(view.id)).blocker
    await runtime.close()


@pytest.mark.parametrize("purpose", ["launch", "handoff"])
@pytest.mark.parametrize("kind", ["denied", "waiting", "expired", "fingerprint"])
async def test_invalid_authorization_blocks_launch_and_handoff(purpose, kind):
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)
    if purpose == "handoff":
        await runtime.advance(view.id)
    authorize = infra.authorize

    async def altered(task, principal, **kwargs):
        approval = await authorize(task, principal, **kwargs)
        if kind in {"denied", "waiting"}:
            return replace(approval, status=ApprovalStatus(kind))
        if kind == "expired":
            return replace(approval, valid_until=clock.now())
        return replace(approval, task_fingerprint="another-task")

    infra.authorize = altered
    blocked = await runtime.advance(view.id)
    assert blocked.step == Step.HYPOTHESIZE
    assert blocked.data["current"] is not None
    assert len(runner.starts) == (1 if purpose == "handoff" else 0)
    expected_reason = "authority" if purpose == "handoff" else "authorization"
    assert expected_reason in blocked.blocker
    infra.authorize = authorize
    resumed = await runtime.advance(view.id)
    assert len(runner.starts) == 1
    if purpose == "handoff":
        assert resumed.step == Step.IMPLEMENT
    await runtime.close()


@pytest.mark.parametrize("kind", ["fingerprint", "stale", "no_evidence"])
async def test_mismatched_or_stale_native_projection_never_advances(kind):
    runtime, _, _, infra, _ = compose()
    read = infra.read_evidence

    async def altered(request, principal):
        result = await read(request, principal)
        if kind == "fingerprint":
            return replace(result, task_fingerprint="another-task")
        if kind == "stale":
            return replace(
                result,
                observed_at=result.observed_at - timedelta(hours=1),
                valid_until=result.observed_at - timedelta(seconds=1),
            )
        return replace(result, evidence=())

    infra.read_evidence = altered
    view = await new(runtime)
    await runtime.advance(view.id)
    blocked = await runtime.advance(view.id)
    assert "mismatched" in blocked.blocker and blocked.step == Step.HYPOTHESIZE
    await runtime.close()


async def test_execution_identity_and_unknown_process_do_not_accept_native_handoff():
    runtime, _, runner, infra, _ = compose()
    view = await new(runtime)
    await runtime.advance(view.id)

    async def wrong(ref):
        return AgentResult(AgentStatus.COMPLETED, envelope(), ExecutionRef("wrong", "wrong"))

    runner.observe = wrong
    assert "identity mismatch" in (await runtime.advance(view.id)).blocker

    async def unknown(ref):
        return AgentResult(AgentStatus.UNKNOWN, execution=ref)

    runner.observe = unknown
    assert "capable of effects" in (await runtime.advance(view.id)).blocker
    infra.overrides["execution_fenced"] = True
    assert (await runtime.advance(view.id)).step == Step.IMPLEMENT
    await runtime.close()


async def test_observation_exception_and_pending_reuse_original_task():
    runtime, clock, runner, _, _ = compose()
    view = await new(runtime)
    await runtime.advance(view.id)
    runner.pending = True
    blocked = await runtime.advance(view.id)
    assert "pending" in blocked.blocker
    for _ in range(3):
        clock.tick(5)
        assert (await runtime.advance(view.id)).revision == blocked.revision
    runner.observe = unavailable
    assert "unknown" in (await runtime.advance(view.id)).blocker
    assert len(runner.starts) == 1
    await runtime.close()


async def test_dispatch_response_identity_mismatch_becomes_observation_not_relaunch():
    runtime, _, runner, _, _ = compose()
    start = runner.start

    async def wrong(task):
        await start(task)
        return ExecutionRef(task.id, "wrong")

    runner.start = wrong
    view = await new(runtime)
    assert "unknown" in (await runtime.advance(view.id)).blocker
    assert (await runtime.advance(view.id)).step == Step.IMPLEMENT
    assert len(runner.starts) == 1
    await runtime.close()


async def test_final_dispatch_fence_blocks_control_change_during_authorization():
    runtime, _, runner, infra, _ = compose()
    view = await new(runtime)
    authorize = infra.authorize

    async def hold_during_authorization(task, principal):
        result = await authorize(task, principal)
        await runtime.hold(view.id)
        return result

    infra.authorize = hold_during_authorization
    with pytest.raises(ConflictError):
        await runtime.advance(view.id)
    assert not runner.starts and (await runtime.inspect(view.id)).status == "held"
    await runtime.close()


async def test_slow_host_result_cannot_commit_after_lease_expires():
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)
    await runtime.advance(view.id)
    read = infra.read_evidence

    async def delayed(request, principal):
        result = await read(request, principal)
        clock.tick(61)
        return result

    infra.read_evidence = delayed
    with pytest.raises(StaleLeaseError):
        await runtime.advance(view.id)
    assert len(runner.starts) == 1
    assert (await runtime.inspect(view.id)).step == Step.HYPOTHESIZE
    await runtime.close()


async def test_concurrent_lease_skips_dispatch():
    runtime, clock, runner, _, _ = compose()
    view = await new(runtime)
    lease = await runtime.store.acquire(view.id, "other", clock.now())
    assert lease is not None
    await runtime.advance(view.id)
    assert not runner.starts
    await runtime.store.release(lease)
    await runtime.advance(view.id)
    assert runner.starts
    await runtime.close()


async def test_prepared_exposure_rechecks_protection_after_wait():
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    infra.approval = ApprovalStatus.WAITING
    await runtime.advance(view.id)
    count = len(runner.starts)
    infra.approval = ApprovalStatus.ALLOWED
    infra.independent_stop_ready = False
    blocked = await runtime.advance(view.id)
    assert "protection" in blocked.blocker and len(runner.starts) == count
    await runtime.close()


async def test_transient_and_sustained_monitor_failure_have_distinct_behavior():
    runtime, clock, _, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    last = clock.now()

    async def degraded(project, run, principal):
        return SafetyStatus(
            False,
            True,
            last,
            last + timedelta(seconds=5),
            "fixture:degraded",
            degraded=True,
            last_success_at=last,
        )

    infra.safety = degraded
    transient = await runtime.advance(view.id)
    assert transient.status == "active" and not infra.stop_requests
    clock.tick(6)
    sustained = await runtime.advance(view.id)
    assert sustained.status == "stopping" and infra.stop_requests
    await runtime.close()


async def test_unavailable_monitor_after_grace_requests_stop_but_not_successful_closure():
    runtime, clock, _, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    active = await runtime.inspect(view.id)
    clock.value = timestamp(active.data["experiment_deadline"])
    infra.safety = unavailable
    pending = await runtime.advance(view.id)
    assert pending.status == "active"
    clock.tick(6)
    stopping = await runtime.advance(view.id)
    assert stopping.status == "stopping" and infra.stop_requests
    await runtime.close()


async def test_changed_serving_candidate_requests_independent_stop():
    runtime, clock, _, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    safety = infra.safety

    async def changed(project, run, principal):
        return replace(
            await safety(project, run, principal), candidate="different", exposure_active=True
        )

    infra.safety = changed
    assert (await runtime.advance(view.id)).status == "stopping"
    assert infra.stop_requests
    await runtime.close()


async def test_promoted_main_identity_remains_valid_during_disposition_observation():
    runtime, clock, _, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.DECIDE, scope="disposition")
    # A proposal alone cannot explain new exposure; authorize and start the
    # actual promotion invocation before observing its native serving state.
    accepted = await runtime.advance(view.id)
    assert accepted.data["task"]["task"]["scope"] == "disposition"
    safety = infra.safety

    async def promoted(project, run, principal):
        return replace(
            await safety(project, run, principal),
            healthy=True,
            exposure_active=True,
            exposure_end=None,
            experiment_id=accepted.data["experiment_id"],
            candidate=accepted.data["candidate"],
            plan_fingerprint=runtime.projects["demo"].plan.fingerprint,
        )

    infra.safety = promoted
    assert (await runtime.advance(view.id)).status == "active"
    assert not infra.stop_requests
    await runtime.close()


async def test_stop_acknowledgment_is_not_applied_protection_or_effective_zero():
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)

    async def ack(request, principal):
        return StopDelivery(request.request_id, True, "fixture:ack-only")

    infra.request_stop = ack
    infra.overrides.update(stop_protection_applied=False, correction_safe=False)
    await runtime.stop(view.id)
    for _ in range(6):
        blocked = await runtime.advance(view.id)
        clock.tick()
    assert blocked.status == "stopping" and not blocked.data.get("cleanup_confirmed")
    assert "stop_protection_applied" in blocked.blocker
    assert all(task.purpose == "reconcile" for task in runner.tasks.values())
    await runtime.close()


async def test_cleanup_budget_is_finite_and_cannot_disable_independent_stop():
    runtime, clock, runner, infra, _ = compose()
    infra.overrides.update(
        stop_protection_applied=False, correction_safe=True, effects_settled=True
    )
    view = await new(runtime)
    await runtime.stop(view.id)
    for _ in range(12):
        blocked = await runtime.advance(view.id)
        clock.tick()
    assert blocked.status == "stopping" and "cleanup allowance" in blocked.blocker
    assert len(runner.starts) == runtime.projects["demo"].cleanup_tasks
    assert infra.stop_requests
    await runtime.close()


async def test_stop_handles_unlaunched_task_without_running_agent():
    runtime, clock, runner, infra, _ = compose()
    infra.approval = ApprovalStatus.WAITING
    view = await new(runtime)
    await runtime.advance(view.id)
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped" and not runner.starts
    assert final.data["reserved_tasks"] == 0
    await runtime.close()


async def test_blocked_result_waits_until_dependency_resolved():
    runtime, _, runner, infra, _ = compose()
    runner.output = envelope(
        "blocked", blocker={"reason": "Need source record", "owner": "maintainer"}
    )
    view = await new(runtime)
    await runtime.advance(view.id)
    blocked = await runtime.advance(view.id)
    assert "maintainer" in blocked.blocker and blocked.step == Step.HYPOTHESIZE
    infra.overrides["blocker_resolved"] = True
    assert (await runtime.advance(view.id)).step == Step.IMPLEMENT
    await runtime.close()


async def test_same_stage_engineering_increment_is_a_new_bounded_invocation():
    runtime, clock, runner, infra, _ = compose()
    view = await new(runtime)
    await drive(runtime, clock, view.id, target=Step.IMPLEMENT)
    infra.overrides.update(
        resume_required=True,
        wake_at=(clock.now() + timedelta(seconds=20)).isoformat(),
        reason="Compile job pending",
    )
    await runtime.advance(view.id)
    yielded = await runtime.advance(view.id)
    assert yielded.step == Step.IMPLEMENT and yielded.data["current"] is None
    count = len(runner.starts)
    await runtime.advance(view.id)
    assert len(runner.starts) == count
    infra.overrides.clear()
    clock.tick(20)
    await runtime.advance(view.id)
    assert len(runner.starts) == count + 1
    assert (await runtime.advance(view.id)).step == Step.EXPERIMENT
    await runtime.close()


@pytest.mark.parametrize(
    "output",
    [
        {},
        envelope(summary=""),
        envelope(deliverable=[]),
        envelope(evidence=[3]),
        envelope(outcome="bogus"),
        envelope("waiting"),
        envelope("waiting", wait={"reason": "native_record"}),
        envelope("waiting", wait={"reason": "timer", "not_before": "bad"}),
        envelope("waiting", wait={"reason": "authority_boundary", "boundary": "all_access"}),
        envelope("failed"),
    ],
)
def test_invalid_result_envelopes_are_actionable(output):
    assert _envelope(AgentResult(AgentStatus.COMPLETED, output))


@pytest.mark.parametrize(
    "wait",
    [
        {"reason": "native_record", "reference": "native:x"},
        {"reason": "authority_boundary", "boundary": "main_exposure"},
        {"reason": "timer", "not_before": "2026-01-01T00:00:00Z"},
    ],
)
def test_supported_wait_envelopes(wait):
    assert _envelope(AgentResult(AgentStatus.COMPLETED, envelope("waiting", wait=wait))) is None


async def test_stop_only_principal_delivers_without_advance_or_private_evidence_access():
    from aced import Principal

    runtime, _, _, infra, identity = compose()
    identity.principal = Principal("worker", frozenset({"run:*", "project:*", "private"}))
    infra.claims = frozenset({"private"})
    view = await new(runtime)
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    identity.principal = Principal(
        "operator", frozenset({"run:stop", "run:inspect", "project:demo"})
    )
    stopped = await runtime.stop(view.id)
    assert stopped.status == "stopping" and stopped.redacted
    assert infra.stop_requests and infra.stop_latched
    await runtime.close()


async def test_stop_delivers_while_other_worker_holds_lease():
    runtime, clock, _, infra, _ = compose()
    view = await new(runtime)
    lease = await runtime.store.acquire(view.id, "other-worker", clock.now())
    assert lease is not None
    stopped = await runtime.stop(view.id)
    assert stopped.status == "stopping" and infra.stop_latched
    assert infra.stop_requests
    await runtime.store.release(lease)
    await runtime.close()


@pytest.mark.parametrize(
    "failure", ["missing_runner", "cancel_error", "wrong_execution", "wrong_delivery"]
)
async def test_stopping_diagnostics_do_not_claim_zero(failure):
    runtime, _, runner, infra, _ = compose()
    view = await new(runtime)
    await runtime.advance(view.id)
    if failure == "missing_runner":
        del runtime.runners["demo"]
    elif failure == "cancel_error":
        runner.cancel = unavailable
    elif failure == "wrong_execution":

        async def wrong(ref):
            return AgentResult(AgentStatus.CANCELLED, execution=ExecutionRef("other", "other"))

        runner.cancel = wrong
    else:

        async def wrong_delivery(request, principal):
            return StopDelivery("different", True, "fixture:wrong")

        infra.request_stop = wrong_delivery
    stopped = await runtime.stop(view.id)
    assert stopped.status == "stopping"
    assert not stopped.data.get("cleanup_confirmed")
    if failure == "wrong_delivery":
        assert stopped.data["stop_delivery_error"] == "ValueError"
    else:
        assert stopped.blocker
    await runtime.close()
