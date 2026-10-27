"""Native fixture receipts must not manufacture the identities a caller expects."""

from dataclasses import replace

import pytest

from aced import EvidenceRequest, Goal, Step
from aced._json import json_value
from aced.runtime import _task
from aced.workflow import InvalidEvidence, complete
from tests.test_runtime import compose, drive


@pytest.mark.parametrize("mismatch", ["candidate", "plan_fingerprint", "task_fingerprint"])
async def test_settlement_returns_native_identity_and_rejects_expected_mismatch(mismatch):
    runtime, clock, runner, infra, identity = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="native-settlement")
    await runtime.advance(view.id)
    original = next(iter(runner.tasks.values()))
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    data = json_value(final.data)
    data["status"] = "stopping"
    expected = runtime._expected(data)
    if mismatch == "task_fingerprint":
        expected["unresolved_tasks"] = [
            {"task_id": original.id, "task_fingerprint": "different-fingerprint"}
        ]
        data["unresolved_tasks"] = expected["unresolved_tasks"]
    else:
        expected[mismatch] = "different-native-identity"
        if mismatch == "candidate":
            data["candidate"] = expected[mismatch]
    request = EvidenceRequest(original, expected=expected, purpose="settlement")
    verified = await infra.read_evidence(request, identity.principal)
    if mismatch == "task_fingerprint":
        assert verified.facts["settled_tasks"] == (
            {"task_id": original.id, "task_fingerprint": original.fingerprint},
        )
    else:
        assert verified.facts[mismatch] != expected[mismatch]
    if mismatch != "plan_fingerprint":
        with pytest.raises(InvalidEvidence):
            complete(data, json_value(verified.facts), runtime.projects["demo"], clock.now())
    await runtime.close()


async def test_immediate_stop_proves_native_absence_without_executing_a_task():
    runtime, clock, runner, infra, identity = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="native-absence")
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped" and not runner.starts
    assert not infra.exposures and not infra.tasks
    receipt = infra.stop_receipts[final.data["stop_request_id"]]
    assert receipt["absent_exposure"]
    assert receipt["identities"]["source_baseline"] == "source-0"
    assert receipt["identities"]["plan_fingerprint"] == infra.native_plan.fingerprint
    assert "candidate" not in receipt["identities"]
    assert "deployment_id" not in receipt["identities"]
    task = _task(final.data["task"]["task"])
    evidence = await infra.read_evidence(
        EvidenceRequest(task, expected={"source_baseline": "unrelated"}, purpose="settlement"),
        identity.principal,
    )
    assert evidence.facts["accepted_source"] == "source-0"
    assert evidence.facts["source_baseline"] == "source-0"
    assert evidence.facts["settled_tasks"] == ()
    await runtime.close()


async def test_frozen_stop_receipt_ignores_changed_read_expectations():
    runtime, clock, runner, infra, identity = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="frozen-stop")
    await runtime.advance(view.id)
    original = next(iter(runner.tasks.values()))
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    request = EvidenceRequest(original, purpose="settlement")
    first = await infra.read_evidence(request, identity.principal)
    second = await infra.read_evidence(
        replace(request, expected={"stop_request_id": "unrelated", "canary_id": "forged"}),
        identity.principal,
    )
    assert first.facts == second.facts
    assert second.facts["stop_request_id"] == final.data["stop_request_id"]
    await runtime.close()


@pytest.mark.parametrize("monitor_first", [False, True])
async def test_delayed_lost_activation_recovery_observes_same_native_deadline(
    tmp_path, monitor_first
):
    database = tmp_path / "fresh-development.sqlite3"
    runtime, clock, runner, infra, identity = compose(database)
    view = await runtime.start(Goal("demo", "Learn"), key="lost-activation-at-expiry")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    runner.lose_start_response = True
    launched = await runtime.advance(view.id)
    task_id = launched.data["current"]
    native = dict(infra.exposures[launched.data["experiment_id"]])
    assert launched.data.get("experiment_deadline") is None
    await runtime.close()
    clock.value = native["end"]
    infra.monitor_first = monitor_first
    runtime, *_ = compose(database, clock=clock, runner=runner, infra=infra, identity=identity)
    recovered = await runtime.advance(view.id)
    assert recovered.status == "active" and not infra.stop_requests
    assert runner.starts.count(task_id) == 1
    assert infra.exposures[recovered.data["experiment_id"]]["end"] == native["end"]
    assert recovered.data["task"]["task"]["id"] == task_id
    if not monitor_first:
        safety = await infra.safety("demo", view.id, identity.principal)
        assert safety.experiment_id == native["id"]
        assert safety.candidate == native["candidate"]
        assert safety.plan_fingerprint == native["plan_fingerprint"]
    await runtime.close()


async def test_failed_cycle_repair_then_stop_uses_new_native_stop_receipt():
    runtime, clock, _, infra, _ = compose()
    infra.repair = True
    view = await runtime.start(Goal("demo", "Learn"), key="repair-second-stop")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    await runtime.advance(view.id)
    infra.healthy = False
    stopping = await runtime.advance(view.id)
    assert stopping.status == "stopping"
    first_stop = stopping.data["stop_request_id"]
    infra.healthy = True
    repaired = await drive(runtime, clock, view.id, target=Step.IMPLEMENT)
    assert repaired.cycle == 2
    assert repaired.data["repair_context"]["stop_request_id"] == first_stop
    assert "stop_request_id" not in repaired.data and "stop_request" not in repaired.data
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    await runtime.advance(view.id)
    await runtime.stop(view.id)
    final = await drive(runtime, clock, view.id)
    assert final.status == "stopped"
    assert final.data["stop_request_id"] != first_stop
    assert len(infra.stop_receipts) == 2
    await runtime.close()


async def test_native_stop_closure_time_does_not_change_on_later_monitor_reads():
    runtime, clock, _, infra, _ = compose()
    view = await runtime.start(Goal("demo", "Learn"), key="native-closure")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    active = await runtime.advance(view.id)
    canary = infra.exposures[active.data["canary_id"]]
    await runtime.stop(view.id)
    ended = canary["ended"]
    assert ended < canary["review_end"]
    clock.tick(100)
    infra.monitor()
    assert canary["ended"] == ended
    await runtime.close()


async def test_late_repair_task_cannot_clear_a_newer_native_stop_latch():
    runtime, clock, runner, infra, _ = compose()
    infra.repair = True
    view = await runtime.start(Goal("demo", "Learn"), key="late-repair")
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT)
    await runtime.advance(view.id)
    infra.healthy = False
    await runtime.advance(view.id)
    infra.healthy = True
    await drive(runtime, clock, view.id, target=Step.IMPLEMENT)
    await drive(runtime, clock, view.id, target=Step.EXPERIMENT, scope="main_exposure")
    queued = []

    async def delayed_start(task):
        queued.append(task)
        raise OSError("native launch request remains in flight")

    runner.start = delayed_start
    await runtime.advance(view.id)
    assert len(queued) == 1 and queued[0].context.get("repair_context")
    await runtime.stop(view.id)
    with pytest.raises(PermissionError, match="late re-exposure"):
        infra.execute(queued[0])
    assert queued[0].context["experiment_id"] not in infra.exposures
    await runtime.close()
