"""Behavioral regressions for the four-stage implementation review."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from aced import (
    ApprovalStatus,
    AuthorizationError,
    ConflictError,
    Goal,
    PlanBounds,
    Principal,
    RunContinuation,
    Step,
    VerificationStatus,
)
from aced._json import json_value
from aced.reference import demo_project
from tests.test_runtime import compose, drive


async def active_main(runtime, clock):
    view = await runtime.start(Goal("demo", "Learn"), key="review")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    return await runtime.inspect(view.id)


async def settle_failure(runtime, clock, infra, run_id):
    infra.healthy = False
    for _ in range(15):
        view = await runtime.advance(run_id)
        if view.step is Step.DECIDE and view.status == "active":
            return view
        clock.tick()
    raise AssertionError(view.blocker)


async def test_retained_incident_reaches_decide_after_restart_without_repeated_cleanup(tmp_path):
    path = tmp_path / "fresh-review.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    infra.continue_cycles = 1
    view = await active_main(runtime, clock)
    settled = await settle_failure(runtime, clock, infra, view.id)
    assert settled.data["cleanup_confirmed"] and not infra.healthy
    original_stop = settled.data["stop_request_id"]
    await runtime.close()
    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.data["outcome"] == "unsuccessful"
    assert final.data["stop_request_id"] == original_stop
    assert len(set(infra.stop_requests)) == 1
    assert final.data["cleanup_count"] == final.data["cleanup_reserved"] == 0
    assert any(t.step == "decide" and t.purpose == "work" for t in runner.tasks.values())
    assert final.data["learning"] and await runtime.store.verify_audit()
    await runtime.close()


async def test_new_exposure_after_settlement_creates_a_new_stop_obligation():
    runtime, clock, _, infra, _ = compose()
    view = await active_main(runtime, clock)
    settled = await settle_failure(runtime, clock, infra, view.id)
    original_stop = settled.data["stop_request_id"]
    observed = infra.safety

    async def reexposed(*args):
        return replace(await observed(*args), exposure_active=True, zero_confirmed=False)

    infra.safety = reexposed
    stopping = await runtime.advance(view.id)
    assert stopping.status in {"stopping", "active"}
    assert stopping.data["stop_request_id"] != original_stop
    assert len(set(infra.stop_requests)) == 2
    await runtime.close()


async def test_native_only_settlement_available_after_all_cleanup_invocations_used():
    cfg = replace(demo_project(Path("/tmp/product")), cleanup_tasks=1)
    runtime, clock, runner, infra, _ = compose(config=cfg)
    view = await active_main(runtime, clock)
    read = infra.read_evidence

    async def needs_agent(request, principal):
        verdict = await read(request, principal)
        if request.task.purpose == "reconcile" and request.result is None:
            return replace(verdict, status=VerificationStatus.UNKNOWN, facts={})
        return verdict

    infra.read_evidence = needs_agent
    settled = await settle_failure(runtime, clock, infra, view.id)
    assert settled.data["cleanup_count"] == settled.data["cleanup_reserved"] == 1
    assert sum(t.purpose == "reconcile" for t in runner.tasks.values()) == 1
    infra.read_evidence = read
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped"
    assert final.data["cleanup_count"] == final.data["cleanup_reserved"] == 1
    assert sum(t.purpose == "reconcile" for t in runner.tasks.values()) == 1
    await runtime.close()


async def test_pending_cleanup_reservation_released_when_native_facts_arrive():
    runtime, clock, runner, infra, _ = compose()
    view = await active_main(runtime, clock)
    read = infra.read_evidence
    native_available = False

    async def pending(request, principal):
        verdict = await read(request, principal)
        if request.task.purpose == "reconcile" and not native_available:
            return replace(verdict, status=VerificationStatus.UNKNOWN, facts={})
        return verdict

    infra.read_evidence = pending
    infra.approval = ApprovalStatus.WAITING
    infra.healthy = False
    for _ in range(8):
        waiting = await runtime.advance(view.id)
        if waiting.data["cleanup_reserved"]:
            break
        clock.tick()
    assert waiting.data["cleanup_reserved"] == 1 and waiting.data["cleanup_count"] == 0
    native_available = True
    runtime.runners.clear()
    settled = await runtime.advance(view.id)
    assert settled.step is Step.DECIDE and settled.data["cleanup_reserved"] == 0
    assert not any(t.purpose == "reconcile" for t in runner.tasks.values())
    await runtime.close()


async def test_worker_handles_early_incident_during_day_long_native_wait():
    cfg = demo_project(Path("/tmp/product"))
    cfg = replace(cfg, plan=replace(cfg.plan, experiment_seconds=86400))
    runtime, clock, runner, infra, _ = compose(config=cfg)
    infra.continue_cycles = 1
    view = await active_main(runtime, clock)
    starts = len(runner.starts)
    clock.tick(5)
    infra.healthy = False
    infra.stop_latched = True
    infra.monitor()
    assert not await runtime.store.list_due(clock.now())
    done = asyncio.Event()
    original = runtime.advance

    async def observed(run_id):
        progressed = await original(run_id)
        if progressed.step is Step.DECIDE and progressed.status == "active":
            done.set()
        return progressed

    runtime.advance = observed
    worker = asyncio.create_task(runtime.run_worker(done, interval=0.001))
    try:
        await asyncio.wait_for(done.wait(), 2)
        await worker
        settled = await runtime.inspect(view.id)
        assert settled.data["cleanup_confirmed"] and settled.data["outcome"] == "unsuccessful"
        assert len(runner.starts) == starts
        assert settled.data["experiment_deadline"] == view.data["experiment_deadline"]
    finally:
        done.set()
        await worker
        await runtime.close()


async def test_expired_launch_authority_does_not_prevent_long_experiment_readout():
    cfg = demo_project(Path("/tmp/product"))
    cfg = replace(cfg, plan=replace(cfg.plan, experiment_seconds=86400))
    runtime, clock, runner, infra, _ = compose(config=cfg)
    infra.continue_cycles = 1
    authorize = infra.authorize
    accepted_late = []

    async def scoped_authority(task, principal, *, purpose="dispatch"):
        approval = await authorize(task, principal, purpose=purpose)
        if clock.now() >= task.deadline:
            if purpose == "dispatch":
                return replace(approval, status=ApprovalStatus.DENIED)
            accepted_late.append(task.id)
        return approval

    infra.authorize = scoped_authority
    view = await active_main(runtime, clock)
    task = next(t for t in runner.tasks.values() if t.scope == "main_exposure")
    clock.tick(86401)
    final = await drive(runtime, clock, view.id)
    assert task.id in accepted_late
    assert final.status == "completed" and final.data["learning"]
    assert sum(t.scope == "main_exposure" for t in runner.tasks.values()) == 1
    await runtime.close()


async def test_selected_continuity_is_authorized_bound_and_in_first_research_task(tmp_path):
    runtime, clock, runner, infra, identity = compose(tmp_path / "fresh-continuity.sqlite3")
    previous = await runtime.start(Goal("demo", "First"), key="first")
    final = await drive(runtime, clock, previous.id)
    runtime.projects["demo"] = replace(
        runtime.projects["demo"], source_revision=final.data["retained_source"]
    )
    selection = RunContinuation(
        final.id,
        final.data["retained_source"],
        learning_references=(final.data["learning"][-1]["reference"],),
        candidate_ids=("candidate-a",),
    )
    next_run = await runtime.start(Goal("demo", "Second"), key="second", continuation=selection)
    assert next_run.data["continuity_source"]["revision"] == final.revision
    assert len(next_run.data["learning"]) == len(next_run.data["research_candidates"]) == 1
    await runtime.advance(next_run.id)
    task = next(t for t in runner.tasks.values() if t.run_id == next_run.id)
    assert task.context["continuity"]["previous_run_id"] == previous.id
    assert task.context["learning"][0]["reference"] == selection.learning_references[0]
    assert task.context["research_candidates"][0]["outcomes"]
    with pytest.raises(ConflictError, match="continuity"):
        await runtime.start(
            Goal("demo", "Second"),
            key="second",
            continuation=replace(selection, candidate_ids=("candidate-b",)),
        )
    await runtime.close()


async def test_cross_run_learning_cannot_bypass_evidence_claims():
    runtime, clock, _, infra, identity = compose()
    identity.principal = Principal("worker", frozenset({"run:*", "project:*", "private"}))
    infra.claims = frozenset({"private"})
    previous = await runtime.start(Goal("demo", "First"), key="first")
    final = await drive(runtime, clock, previous.id)
    runtime.projects["demo"] = replace(
        runtime.projects["demo"], source_revision=final.data["retained_source"]
    )
    identity.principal = Principal("operator", frozenset({"run:*", "project:*"}))
    with pytest.raises(AuthorizationError, match="evidence claims"):
        await runtime.start(
            Goal("demo", "Second"),
            key="second",
            continuation=RunContinuation(previous.id, final.data["retained_source"]),
        )
    await runtime.close()


async def test_second_phase_accepts_changed_plan_and_recovers_frozen_plan(tmp_path):
    cfg = demo_project(Path("/tmp/product"))
    bounds = PlanBounds(
        metrics=("activation", "conversion"),
        decision_rules=(cfg.plan.decision_rule,),
        required_guardrails=cfg.plan.guardrails,
        max_canary_percent=5,
        max_experiment_percent=25,
        max_canary_seconds=60,
        max_experiment_seconds=60,
        max_monitor_grace_seconds=5,
    )
    cfg = replace(cfg, plan_bounds=bounds)
    runtime, clock, runner, infra, identity = compose(tmp_path / "fresh-phases.sqlite3", config=cfg)
    execute = infra.execute
    second_plan = replace(cfg.plan, metric="conversion", experiment_seconds=20)

    def choose_phase_plan(task):
        execute(task)
        if task.scope == "research" and task.cycle == 2:
            infra.ledger[task.id].update(
                plan=json_value(second_plan),
                plan_fingerprint=second_plan.fingerprint,
                plan_authorization_fingerprint=second_plan.fingerprint,
            )

    infra.execute = choose_phase_plan
    view = await runtime.start(Goal("demo", "Linked phases"), key="phases")
    for _ in range(90):
        progress = await runtime.inspect(view.id)
        if progress.cycle == 2 and progress.step is Step.IMPLEMENT:
            break
        if progress.wake_at:
            from aced.workflow import timestamp

            clock.value = max(clock.value, timestamp(progress.wake_at))
        await runtime.advance(view.id)
        clock.tick()
    else:
        raise AssertionError(progress.blocker)
    assert progress.data["cycle_plan"]["metric"] == "conversion"
    assert progress.data["config"]["plan"]["metric"] == "activation"
    await runtime.close()
    runtime, *_ = compose(
        tmp_path / "fresh-phases.sqlite3",
        config=cfg,
        clock=clock,
        runner=runner,
        infra=infra,
        identity=identity,
    )
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.cycle == 2
    implementations = [t for t in runner.tasks.values() if t.step == "implement"]
    assert [t.context["plan"]["metric"] for t in implementations] == [
        "activation",
        "conversion",
    ]
    assert implementations[1].context["source_baseline"] == "source-1"
    windows = [item for item in infra.exposures.values() if item["kind"] == "main"]
    assert [(item["end"] - item["start"]).total_seconds() for item in windows] == [10, 20]
    assert await runtime.store.verify_audit()
    await runtime.close()
