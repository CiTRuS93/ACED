import pytest

from aced import AgentResult, AgentStatus, Goal, Step, VerificationStatus
from aced.reference import envelope
from aced.workflow import timestamp
from tests.test_runtime import compose, drive


@pytest.mark.parametrize("monitor_first", [False, True])
async def test_both_expiry_orderings_reach_same_closed_mature_learning(monitor_first):
    runtime, clock, runner, infra, _ = compose()
    infra.continue_cycles = 1
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    active = await runtime.inspect(view.id)
    deadline = timestamp(active.data["experiment_deadline"])
    calls = len(runner.starts)
    infra.monitor_first = monitor_first
    clock.value = deadline
    expired = await runtime.advance(view.id)
    assert expired.status == "active" and not infra.stop_requests
    assert expired.step == Step.EXPERIMENT
    infra.monitor()
    infra.monitor_first = True
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.data["outcome"] == "promote"
    assert len(runner.starts) == calls + 2
    await runtime.close()


async def test_lost_activation_response_can_reconcile_to_original_healthy_active_operation(
    tmp_path,
):
    path = tmp_path / "state.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    runner.lose_start_response = True
    launched = await runtime.advance(view.id)
    original_id = launched.data["current"]
    exposed = dict(infra.exposures[launched.data["experiment_id"]])
    await runtime.close()
    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    observed = await runtime.advance(view.id)
    assert observed.data["current"] == original_id
    assert observed.data["task"]["status"] == "waiting"
    assert observed.status == "active" and not infra.stop_requests
    assert infra.exposures[observed.data["experiment_id"]]["end"] == exposed["end"]
    assert runner.starts.count(original_id) == 1
    await runtime.close()


async def test_stop_delivers_before_cancel_and_retries_same_lost_delivery_id():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    runner.pending = True
    infra.lose_stop_response = True
    order = []
    stop, cancel = infra.request_stop, runner.cancel

    async def request(request, principal):
        order.append("stop")
        return await stop(request, principal)

    async def cancellation(ref):
        order.append("cancel")
        return await cancel(ref)

    infra.request_stop, runner.cancel = request, cancellation
    await runtime.stop(view.id)
    assert order.index("stop") < order.index("cancel")
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped"  # Native applied proof can supersede lost delivery response.
    assert len(set(infra.stop_requests)) == 1
    assert final.data["stop_delivery_error"] == "OSError"
    await runtime.close()


async def test_unknown_execution_blocks_cleanup_until_authoritatively_fenced():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)

    async def unknown(ref):
        return AgentResult(AgentStatus.UNKNOWN, execution=ref)

    runner.cancel = runner.observe = unknown
    held = await runtime.hold(view.id)
    assert held.status == "held"
    view = await runtime.stop(view.id)
    assert view.status == "stopping" and "not terminal" in view.blocker
    assert len(runner.starts) == 1 and infra.stop_latched
    infra.overrides["execution_fenced"] = True
    await runtime.advance(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped" and final.data["hold_requested"]
    await runtime.close()


async def test_operator_stop_cannot_turn_into_repair():
    runtime, clock, _, infra, _ = compose()
    infra.repair = True
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped" and final.cycle == 1
    await runtime.close()


async def test_unsuccessful_canary_repair_preserves_baseline_plan_and_fresh_identity():
    runtime, clock, runner, infra, _ = compose()
    infra.unsuccessful, infra.repair, infra.continue_cycles = True, True, 2
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.cycle == 2
    assert final.data["learning"][0]["outcome"] == "unsuccessful"
    repair = next(
        task for task in runner.tasks.values() if task.cycle == 2 and task.step == "implement"
    )
    original = next(
        task for task in runner.tasks.values() if task.cycle == 1 and task.step == "implement"
    )
    assert repair.context["source_baseline"] == original.context["source_baseline"] == "source-0"
    assert repair.context["hypothesis"] == original.context["hypothesis"]
    assert repair.context["plan"] == original.context["plan"]
    assert repair.context["canary_id"] != original.context["canary_id"]
    assert repair.context["repair_context"]["candidate"] == "source-1"
    assert not any(task.cycle == 2 and task.step == "hypothesize" for task in runner.tasks.values())
    await runtime.close()


async def test_safe_abandonment_before_exposure_reaches_decision_without_fake_main():
    runtime, clock, _, infra, _ = compose()
    infra.continue_cycles = 1
    infra.overrides.update(
        unsuccessful=True,
        zero_confirmed=True,
        main_started=False,
        reason="Evidence rules out useful implementation",
    )
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    accepted = await runtime.advance(view.id)
    assert accepted.step == Step.DECIDE and not infra.exposures
    infra.overrides.clear()
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.data["goal_assessment"] == "undetermined"
    await runtime.close()


async def test_bounded_reporting_correction_retains_original_output_once():
    runtime, clock, runner, infra, _ = compose()
    runner.output = {"invalid": "original immutable response"}
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    original = (await runtime.tasks(view.id))[0]
    assert original["result"]["output"] == runner.output
    runner.output = envelope()
    corrected = await runtime.advance(view.id)
    assert corrected.data["task"]["task"]["scope"] == "correction"
    assert (
        corrected.data["task"]["task"]["context"]["retry_feedback"]["task_id"]
        == original["task"]["id"]
    )
    assert (await runtime.advance(view.id)).step == Step.IMPLEMENT
    assert (await runtime.tasks(view.id))[0]["result"] == original["result"]
    await runtime.close()


async def test_repeated_unusable_output_exhausts_correction_budget_not_whole_history():
    runtime, _, runner, _, _ = compose()
    runner.output = {"invalid": True}
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    for _ in range(10):
        view = await runtime.advance(view.id)
    assert "correction limit" in view.blocker
    assert len(runner.starts) == 3
    events = len(await runtime.history(view.id))
    for _ in range(20):
        await runtime.advance(view.id)
    assert len(await runtime.history(view.id)) == events
    assert len(await runtime.tasks(view.id)) == 3
    await runtime.close()


async def test_rejection_without_settled_effects_never_authorizes_correction():
    runtime, clock, runner, infra, _ = compose()
    infra.verification = VerificationStatus.REJECTED
    infra.overrides["effects_settled"] = False
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    for _ in range(10):
        await runtime.advance(view.id)
        clock.tick(10)
    assert len(runner.starts) == 1
    assert "unresolved" in (await runtime.inspect(view.id)).blocker
    await runtime.close()


async def test_missing_telemetry_blocks_main_without_manufacturing_health():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    infra.overrides.update(telemetry_verified=False, correction_safe=False)
    await runtime.advance(view.id)
    await runtime.advance(view.id)
    blocked = await runtime.inspect(view.id)
    assert blocked.step == Step.EXPERIMENT and blocked.data["scope"] == "preparation_canary"
    assert "telemetry_verified" in blocked.blocker
    assert not any(task.scope == "main_exposure" for task in runner.tasks.values())
    await runtime.close()


async def test_deadline_cancellation_does_not_assert_product_zero():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="k")
    await runtime.advance(view.id)
    runner.pending = True
    infra.verification = VerificationStatus.UNKNOWN
    clock.tick(901)
    expired = await runtime.advance(view.id)
    assert runner.cancelled and expired.status == "active"
    assert expired.data["current"] is not None
    assert not expired.data.get("cleanup_confirmed")
    await runtime.close()
