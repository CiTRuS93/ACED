from dataclasses import replace
from datetime import timedelta

import pytest

from aced import Goal, SafetyStatus, Step
from aced.workflow import timestamp
from tests.test_runtime import compose, drive


@pytest.mark.parametrize(
    "outcome,valid", [("inconclusive", True), ("promote", False), ("revert", True)]
)
async def test_business_uncertainty_preserves_exposure_and_readout_across_restart(
    tmp_path, outcome, valid
):
    path = tmp_path / "business-uncertainty.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    infra.continue_cycles = 1
    view = await runtime.start(Goal("demo", "Learn"), key="business-uncertainty")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    active = await runtime.advance(view.id)
    original_id = active.data["experiment_id"]
    original_deadline = active.data["experiment_deadline"]
    infra.outcome, infra.valid_result = outcome, valid

    clock.tick()
    pending = await runtime.advance(view.id)
    assert pending.status == "active" and pending.step is Step.EXPERIMENT
    assert pending.data["experiment_deadline"] == original_deadline
    assert not infra.exposures[original_id]["zero"] and not infra.stop_requests
    await runtime.close()

    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    pending = await runtime.advance(view.id)
    assert pending.data["experiment_id"] == original_id
    assert pending.data["experiment_deadline"] == original_deadline
    assert not infra.exposures[original_id]["zero"] and not infra.stop_requests

    clock.value = timestamp(original_deadline)
    readout_wait = await runtime.advance(view.id)
    assert readout_wait.step is Step.EXPERIMENT and readout_wait.data["experiment_zero"]
    assert not infra.stop_requests
    decision = await drive(runtime, clock, view.id, target=Step.DECIDE)
    assert decision.data["outcome"] == (outcome if valid else "inconclusive")
    assert decision.data["experiment_deadline"] == original_deadline
    assert clock.now() >= timestamp(original_deadline) + timedelta(
        seconds=runtime.projects["demo"].plan.readout_delay_seconds
    )
    final = await drive(runtime, clock, view.id)
    assert final.status == "completed" and final.data["retained_source"] == "source-0"
    assert not infra.stop_requests
    await runtime.close()


async def test_operational_failure_stops_an_inconclusive_experiment():
    runtime, clock, _, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="operational-failure")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    active = await runtime.advance(view.id)
    infra.outcome, infra.valid_result, infra.healthy = "inconclusive", False, False

    stopping = await runtime.advance(view.id)
    assert stopping.status == "stopping" and infra.stop_requests
    assert stopping.data["stop_cause"] == "failure"
    assert clock.now() < timestamp(active.data["experiment_deadline"])
    assert infra.exposures[active.data["experiment_id"]]["zero"]
    await runtime.close()


async def test_exposure_requires_independent_stop_before_preparation():
    runtime, clock, runner, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="required-protection")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    calls = len(runner.starts)
    infra.independent_stop_ready = False

    pending = await runtime.advance(view.id)
    assert pending.status == "active" and pending.data["scope"] == "preparation_canary"
    assert pending.blocker and len(runner.starts) == calls
    assert not infra.exposures and not infra.stop_requests
    await runtime.close()


@pytest.mark.parametrize("scope", ["preparation_canary", "main_exposure"])
async def test_healthy_positive_exposure_past_closure_grace_requests_stop(tmp_path, scope):
    path = tmp_path / "overdue-exposure.sqlite3"
    runtime, clock, runner, infra, identity = compose(path)
    view = await runtime.start(Goal("demo", "Learn"), key="overdue-exposure")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope=scope)
    await runtime.advance(view.id)
    active = await runtime.advance(view.id)
    prefix = "canary" if scope == "preparation_canary" else "experiment"
    exposure_id = active.data[f"{prefix}_id"]
    deadline = timestamp(active.data[f"{prefix}_deadline"])
    infra.outcome, infra.valid_result = "inconclusive", False
    monitor, safety = infra.monitor, infra.safety
    infra.monitor = lambda: None

    async def positive(project, run, principal):
        return SafetyStatus(
            True,
            True,
            clock.now(),
            clock.now() + timedelta(seconds=30),
            "fixture:healthy-positive-exposure",
            exposure_active=True,
            exposure_end=deadline,
            experiment_id=exposure_id,
            candidate=active.data["candidate"],
            plan_fingerprint=active.data["plan_fingerprint"],
        )

    infra.safety = positive
    clock.value = deadline
    closure_wait = await runtime.advance(view.id)
    assert closure_wait.status == "active" and not infra.stop_requests
    clock.tick(runtime.projects["demo"].plan.monitor_grace_seconds)
    overdue = await runtime.advance(view.id)
    assert overdue.status == "stopping" and infra.stop_requests
    assert overdue.data["stop_cause"] == "failure"
    assert not infra.exposures[exposure_id]["zero"]
    stop_id = overdue.data["stop_request_id"]
    await runtime.close()

    runtime, *_ = compose(path, clock=clock, runner=runner, infra=infra, identity=identity)
    recovered = await runtime.advance(view.id)
    assert recovered.status == "stopping" and recovered.data["stop_request_id"] == stop_id
    assert set(infra.stop_requests) == {stop_id}
    assert not infra.exposures[exposure_id]["zero"]

    infra.monitor, infra.safety = monitor, safety
    infra.monitor()
    decision = await drive(runtime, clock, view.id, target=Step.DECIDE)
    assert decision.data["outcome"] == "unsuccessful"
    assert decision.data["stop_request_id"] == stop_id
    assert infra.exposures[exposure_id]["zero"]
    await runtime.close()


async def test_authorized_promotion_is_allowed_after_experiment_closure_grace():
    runtime, clock, _, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="authorized-promotion")
    await drive(runtime, clock, view.id, target=Step.DECIDE, scope="disposition")
    accepted = await runtime.advance(view.id)
    clock.value = max(
        clock.now(),
        timestamp(accepted.data["experiment_deadline"])
        + timedelta(seconds=runtime.projects["demo"].plan.monitor_grace_seconds + 1),
    )
    observed = infra.safety

    async def promoted(project, run, principal):
        return replace(
            await observed(project, run, principal),
            healthy=True,
            exposure_active=True,
            zero_confirmed=False,
            exposure_end=None,
            experiment_id=accepted.data["experiment_id"],
            candidate=accepted.data["candidate"],
            plan_fingerprint=accepted.data["plan_fingerprint"],
        )

    infra.safety = promoted
    await runtime.advance(view.id)
    assert not infra.stop_requests
    await runtime.close()


async def test_overdue_exposure_preserves_known_operational_stop_reason():
    runtime, clock, _, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="overdue-operational-failure")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    active = await runtime.advance(view.id)
    deadline = timestamp(active.data["experiment_deadline"])
    clock.value = deadline + timedelta(seconds=runtime.projects["demo"].plan.monitor_grace_seconds)
    infra.monitor = lambda: None

    async def failed(project, run, principal):
        return SafetyStatus(
            False,
            True,
            clock.now(),
            clock.now() + timedelta(seconds=30),
            "fixture:operational-failure",
            reason="error rate exceeded the frozen guardrail",
            exposure_active=True,
            exposure_end=deadline,
            stop_required=True,
            experiment_id=active.data["experiment_id"],
            candidate=active.data["candidate"],
            plan_fingerprint=active.data["plan_fingerprint"],
        )

    infra.safety = failed
    stopping = await runtime.advance(view.id)
    assert stopping.status == "stopping" and infra.stop_requests
    assert stopping.data["stop_reason"] == "error rate exceeded the frozen guardrail"
    await runtime.close()
