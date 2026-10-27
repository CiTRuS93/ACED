import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from aced import (
    ApprovalStatus,
    AuthorizationError,
    ConflictError,
    Goal,
    Principal,
    Runtime,
    Step,
    VerificationStatus,
)
from aced.reference import DemoClock, DemoIdentity, DemoInfrastructure, DemoRunner, demo_project
from aced.workflow import timestamp


def compose(path=":memory:", **overrides):
    clock = overrides.pop("clock", DemoClock())
    infra = overrides.pop("infra", DemoInfrastructure(clock))
    runner = overrides.pop("runner", DemoRunner(infra))
    if isinstance(runner, DemoRunner):
        runner.infrastructure = infra
    identity = overrides.pop("identity", DemoIdentity())
    config = overrides.pop("config", demo_project(Path("/tmp/dedicated-product-workspace")))
    runtime = Runtime(
        path,
        projects={"demo": config},
        runners={"demo": runner},
        infrastructure=infra,
        identity_provider=identity,
        auth_context=None,
        clock=clock,
        **overrides,
    )
    return runtime, clock, runner, infra, identity


async def drive(runtime, clock, run_id, *, target=None, scope=None, steps=300):
    for _ in range(steps):
        view = await runtime.inspect(run_id)
        if view.status in {"completed", "stopped"} or (
            target and view.step == target and (not scope or view.data["scope"] == scope)
        ):
            return view
        if view.wake_at:
            clock.value = max(clock.value, timestamp(view.wake_at))
        await runtime.advance(run_id)
        clock.tick()
    raise AssertionError((await runtime.inspect(run_id)).blocker)


async def test_normal_cycle_restart_source_learning_candidates_and_phases(tmp_path):
    path = tmp_path / "four-stage.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    goal = Goal("demo", "Improve activation")
    view = await runtime.start(goal, key="activation")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    await runtime.close()
    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.cycle == 2
    assert final.data["retained_source"] == "source-2"
    assert len(final.data["learning"]) == 2
    assert final.data["learning"][0]["initiative"]["id"] == "initiative-1"
    second = next(t for t in runner.tasks.values() if t.cycle == 2 and t.step == "hypothesize")
    assert second.context["source_baseline"] == "source-1"
    assert second.context["research_candidates"][0]["outcomes"][0]["outcome"] == "promote"
    assert len(runner.starts) == 12 and len(set(runner.starts)) == 12
    assert {task.step for task in runner.tasks.values()} == {step.value for step in Step}
    assert (await runtime.start(goal, key="activation")).id == view.id
    assert await runtime.store.verify_audit()
    assert len(await runtime.tasks(view.id, limit=3)) == 3
    assert len(await runtime.history(view.id, limit=2)) == 2
    await runtime.close()


@pytest.mark.parametrize(
    "outcome,valid", [("revert", True), ("inconclusive", True), ("promote", False)]
)
async def test_nonwinning_cycles_complete_learning_without_goal_success(outcome, valid):
    runtime, clock, _, infra, _ = compose()
    infra.outcome, infra.valid_result, infra.continue_cycles = outcome, valid, 1
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed"
    assert final.data["retained_source"] == "source-0"
    assert final.data["goal_assessment"] == "undetermined"
    await runtime.close()


async def test_approval_wait_denial_and_proposal_identity_are_durable(tmp_path):
    runtime, clock, runner, infra, _ = compose(tmp_path / "state.sqlite3")
    infra.approval = ApprovalStatus.WAITING
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    view = await runtime.advance(view.id)
    original = view.data["task"]["task"]
    assert not runner.starts and view.data["task_count"] == 0
    for _ in range(5):
        clock.tick(10)
        same = await runtime.advance(view.id)
        assert same.revision == view.revision
    infra.approval = ApprovalStatus.DENIED
    denied = await runtime.advance(view.id)
    assert "denied" in denied.blocker and denied.status == "active"
    clock.tick(1000)
    infra.approval = ApprovalStatus.ALLOWED
    expired = await runtime.advance(view.id)
    assert "expired" in expired.blocker and not runner.starts
    await runtime.repropose(view.id)
    fresh = await runtime.advance(view.id)
    assert fresh.data["current"] != original["id"]
    assert fresh.data["reserved_tasks"] == 1
    assert len(runner.starts) == 1
    with pytest.raises(ValueError):
        await runtime.repropose(view.id)
    await runtime.close()


async def test_lost_launch_response_fresh_session_observes_original(tmp_path):
    path = tmp_path / "state.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    runner.lose_start_response = True
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    view = await runtime.advance(view.id)
    assert "unknown" in view.blocker
    await runtime.close()
    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    view = await runtime.advance(view.id)
    assert view.step == Step.IMPLEMENT and len(runner.starts) == 1
    assert view.data["task_count"] == 1
    await runtime.close()


async def test_routing_is_frozen_but_future_tasks_can_use_new_runner():
    runtime, _, original, infra, _ = compose()
    other = DemoRunner(infra)
    runtime.runners["other"] = other
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    runtime.projects["demo"] = replace(runtime.projects["demo"], default_agent="other")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    assert len(original.starts) == len(other.starts) == 1
    assert next(iter(other.tasks.values())).step == "implement"
    del runtime.runners["other"]
    assert "not registered" in (await runtime.advance(view.id)).blocker
    await runtime.close()


async def test_completed_output_saved_once_while_native_record_pending():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    infra.verification = VerificationStatus.WAITING
    view = await runtime.advance(view.id)
    assert "result" not in view.data["task"]
    events = len(await runtime.history(view.id))
    for _ in range(15):
        clock.tick(10)
        assert (await runtime.advance(view.id)).revision == view.revision
    assert len(await runtime.history(view.id)) == events
    assert runner.observations == 1
    infra.verification = VerificationStatus.VERIFIED
    assert (await runtime.advance(view.id)).step == Step.IMPLEMENT
    assert len(runner.starts) == 1
    await runtime.close()


async def test_hold_accepts_finished_facts_but_never_launches_ordinary_work():
    runtime, clock, runner, _, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    with pytest.raises(ValueError):
        await runtime.resume(view.id)
    await runtime.advance(view.id)
    await runtime.hold(view.id)
    accepted = await runtime.advance(view.id)
    assert accepted.status == "held" and accepted.step == Step.IMPLEMENT
    waiting = await runtime.advance(view.id)
    for _ in range(5):
        clock.tick(10)
        assert (await runtime.advance(view.id)).revision == waiting.revision
    assert len(runner.starts) == 1
    await runtime.resume(view.id)
    await runtime.advance(view.id)
    assert len(runner.starts) == 2
    await runtime.close()


async def test_permissions_redaction_and_shared_resource_ownership():
    runtime, _, _, infra, identity = compose()
    goal = Goal("demo", "Learn")
    with pytest.raises(ValueError):
        await runtime.start(goal, key=" bad ")
    view = await runtime.start(goal, key="k")
    with pytest.raises(ConflictError):
        await runtime.start(Goal("demo", "Changed"), key="k")
    runtime.projects["other"] = replace(runtime.projects["demo"], project_id="other")
    with pytest.raises(ConflictError):
        await runtime.start(Goal("other", "Same shop"), key="k")
    identity.principal = Principal("intruder", frozenset({"run:*", "project:other"}))
    with pytest.raises(AuthorizationError):
        await runtime.inspect(view.id)
    identity.principal = Principal("service", frozenset({"run:*", "project:*", "private"}))
    infra.claims = frozenset({"private"})
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    identity.principal = Principal("reader", frozenset({"run:*", "project:*"}))
    redacted = await runtime.inspect(view.id)
    assert redacted.redacted and not redacted.data
    with pytest.raises(AuthorizationError):
        await runtime.history(view.id)
    with pytest.raises(AuthorizationError):
        await runtime.tasks(view.id)
    await runtime.close()


async def test_observation_hints_coalesce_and_reauthorize():
    runtime, _, runner, _, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    with pytest.raises(ValueError):
        await runtime.record_observation(view.id, " ")
    first = await runtime.record_observation(view.id, "host:notice")
    assert (await runtime.record_observation(view.id, "host:notice")).revision == first.revision
    await runtime.advance(view.id)
    assert next(iter(runner.tasks.values())).context["observation_reference"] == "host:notice"
    await runtime.close()


async def test_budget_exhaustion_waits_for_explicit_stop_and_cleanup_has_own_allowance():
    runtime, clock, runner, _, _ = compose(
        config=replace(demo_project(Path("/tmp/product")), max_tasks=1)
    )
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    blocked = await runtime.advance(view.id)
    assert "budget exhausted" in blocked.blocker and blocked.status == "active"
    assert len(runner.starts) == 1
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped" and final.data["cleanup_confirmed"]
    assert final.data["learning_unavailable"]
    assert (await runtime.stop(view.id)).status == "stopped"
    assert (await runtime.advance(view.id)).status == "stopped"
    await runtime.close()


async def test_worker_uses_same_progression_and_stops_without_product_claim():
    runtime, _, runner, _, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    stop = asyncio.Event()

    async def start(task):
        stop.set()
        return await DemoRunner.start(runner, task)

    runner.start = start
    await runtime.run_worker(stop, interval=0.001)
    assert runner.starts and (await runtime.inspect(view.id)).step == Step.HYPOTHESIZE
    with pytest.raises(ValueError):
        await runtime.run_worker(stop, interval=0)
    await runtime.close()


@pytest.mark.parametrize("seconds", [0, -1, True, 1.5, "60", None])
def test_invalid_lease(seconds):
    with pytest.raises(ValueError):
        compose(lease_seconds=seconds)


@pytest.mark.parametrize(
    "overrides",
    [{"profile": "production"}, {"host_timeout_seconds": 0}, {"host_timeout_seconds": 60}],
)
def test_invalid_runtime_policy(overrides):
    with pytest.raises(ValueError):
        compose(**overrides)


def test_invalid_registrations():
    config = demo_project(Path("/tmp/product"))
    args = dict(
        infrastructure=DemoInfrastructure(DemoClock()),
        identity_provider=DemoIdentity(),
        auth_context=None,
    )
    with pytest.raises(ValueError):
        Runtime(":memory:", projects={"wrong": config}, runners={"demo": DemoRunner()}, **args)
    with pytest.raises(ValueError):
        Runtime(":memory:", projects={"demo": config}, runners={}, **args)
