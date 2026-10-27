"""A retained settled incident must not make a held read-only diagnosis unreachable."""

from dataclasses import replace
from datetime import timedelta

import pytest

from aced import Step
from tests.test_review_corrections import active_main
from tests.test_runtime import compose, drive


async def held_settled_failure():
    runtime, clock, runner, infra, identity = compose()
    infra.continue_cycles = 1
    view = await active_main(runtime, clock)
    await runtime.hold(view.id)
    infra.healthy = False
    for _ in range(15):
        view = await runtime.advance(view.id)
        if view.step is Step.DECIDE and view.data.get("cleanup_confirmed"):
            assert view.status == "held" and view.data["experiment_zero"]
            return runtime, clock, runner, infra, identity, view
        clock.tick()
    raise AssertionError(view.blocker)


async def test_held_settled_incident_can_resume_read_only_decide_without_resetting_incident():
    runtime, clock, runner, infra, _, held = await held_settled_failure()
    stop_id = held.data["stop_request_id"]
    resumed = await runtime.resume(held.id)
    assert resumed.status == "active" and resumed.step is Step.DECIDE
    assert infra.healthy is False and resumed.data["stop_request_id"] == stop_id
    final = await drive(runtime, clock, held.id)
    assert final.status == "completed" and final.data["outcome"] == "unsuccessful"
    assert len(set(infra.stop_requests)) == 1
    assert any(task.scope == "decision" for task in runner.tasks.values())
    await runtime.close()


@pytest.mark.parametrize(
    "case",
    ["stale", "future", "unknown_exposure", "active_exposure", "zero_unknown", "stop_not_ready"],
)
async def test_resume_settled_diagnosis_requires_fresh_protected_zero(case):
    runtime, clock, _, infra, _, held = await held_settled_failure()
    original = infra.safety

    async def unsafe(*args):
        value = await original(*args)
        changes = {
            "stale": {
                "observed_at": clock.now() - timedelta(seconds=2),
                "valid_until": clock.now() - timedelta(seconds=1),
            },
            "future": {
                "observed_at": clock.now() + timedelta(seconds=1),
                "valid_until": clock.now() + timedelta(seconds=2),
            },
            "unknown_exposure": {"exposure_active": None},
            "active_exposure": {"exposure_active": True},
            "zero_unknown": {"zero_confirmed": False},
            "stop_not_ready": {"independent_stop_ready": False},
        }[case]
        return replace(value, **changes)

    infra.safety = unsafe
    with pytest.raises(ValueError, match="fresh safe"):
        await runtime.resume(held.id)
    assert (await runtime.inspect(held.id)).status == "held"
    await runtime.close()
