"""Cycle-plan admission and selected cross-run lineage are explicit durable contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from aced import ApprovalPolicy, PlanBounds, RunContinuation, Step
from aced._json import json_value
from aced.workflow import InvalidEvidence, complete, continuation_seed, request_stop
from tests.test_models_workflow import NOW, config, implementation, research, state


def bounded_config(tmp_path: Path):
    return replace(
        config(tmp_path),
        plan_bounds=PlanBounds(
            metrics=("conversion", "revenue"),
            decision_rules=("native-rule", "revenue-rule"),
            required_guardrails=("errors", "latency"),
            max_canary_percent=5,
            max_experiment_percent=25,
            max_canary_seconds=60,
            max_experiment_seconds=120,
            max_monitor_grace_seconds=5,
            min_canary_samples=10,
            min_canary_seconds=3,
            min_readout_delay_seconds=2,
            min_observation_seconds=2,
        ),
    )


def proposed_research(settings, plan, **updates):
    return research(
        settings,
        plan=json_value(plan),
        plan_fingerprint=plan.fingerprint,
        plan_authorization_fingerprint=plan.fingerprint,
        **updates,
    )


def test_new_phase_admits_its_complete_authorized_plan_and_freezes_it(tmp_path):
    settings = bounded_config(tmp_path)
    second = replace(
        settings.plan,
        metric="revenue",
        decision_rule="revenue-rule",
        experiment_seconds=30,
        guardrails=("errors", "latency", "refunds"),
    )
    initial = state(Step.HYPOTHESIZE, cycle=2)
    accepted, event = complete(initial, proposed_research(settings, second), settings, NOW)
    assert event == "accepted" and accepted["step"] == "implement"
    assert accepted["cycle_plan"] == json_value(second)
    assert accepted["plan_fingerprint"] == second.fingerprint
    assert accepted["plan_admission"] == {
        "reference": "plan-approval:1",
        "fingerprint": second.fingerprint,
        "cycle": 2,
    }
    assert "cycle_plan" not in initial
    effective = replace(settings, plan=second)
    implemented, event = complete(accepted, implementation(effective), settings, NOW)
    assert event == "accepted" and implemented["step"] == "experiment"
    assert implemented["cycle_plan"] == json_value(second)
    with pytest.raises(InvalidEvidence, match="plan_fingerprint"):
        complete(accepted, implementation(settings), settings, NOW)
    with pytest.raises(InvalidEvidence, match="cannot change"):
        complete(accepted, implementation(effective, plan=json_value(settings.plan)), settings, NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"metric": "unknown"},
        {"decision_rule": "unapproved"},
        {"guardrails": ("errors",)},
        {"canary_percent": 6},
        {"experiment_percent": 26},
        {"canary_max_seconds": 61},
        {"experiment_seconds": 121},
        {"monitor_grace_seconds": 6},
        {"canary_min_samples": 9},
        {"canary_min_seconds": 2},
        {"readout_delay_seconds": 1},
        {"observation_seconds": 1},
    ],
)
def test_plan_cannot_exceed_run_authority_or_weaken_minimums(tmp_path, changes):
    settings = bounded_config(tmp_path)
    proposed = replace(settings.plan, **changes)
    with pytest.raises(InvalidEvidence, match="admission rejected"):
        complete(state(Step.HYPOTHESIZE), proposed_research(settings, proposed), settings, NOW)


@pytest.mark.parametrize(
    "field,value",
    [
        ("plan_authorized", False),
        ("plan_authorization_reference", ""),
        ("plan_authorization_fingerprint", "old-plan"),
        ("plan_fingerprint", "old-plan"),
    ],
)
def test_plan_requires_exact_current_authorization_evidence(tmp_path, field, value):
    settings = bounded_config(tmp_path)
    facts = proposed_research(settings, settings.plan)
    facts[field] = value
    with pytest.raises(InvalidEvidence):
        complete(state(Step.HYPOTHESIZE), facts, settings, NOW)


def test_fixed_plan_remains_optional_policy_and_cannot_change(tmp_path):
    settings = config(tmp_path)
    accepted, _ = complete(state(Step.HYPOTHESIZE), research(settings), settings, NOW)
    assert accepted["cycle_plan"] == json_value(settings.plan)
    changed = replace(settings.plan, metric="revenue")
    with pytest.raises(InvalidEvidence, match="fixed host policy"):
        complete(state(Step.HYPOTHESIZE), proposed_research(settings, changed), settings, NOW)
    dynamic = bounded_config(tmp_path)
    accepted["step"] = "hypothesize"
    with pytest.raises(InvalidEvidence, match="immutable"):
        complete(accepted, proposed_research(dynamic, changed), dynamic, NOW)


def test_repair_preserves_plan_but_next_hypothesis_requires_new_admission(tmp_path):
    from aced.workflow import _new_cycle

    settings = bounded_config(tmp_path)
    plan = replace(settings.plan, metric="revenue")
    data = state(
        Step.DECIDE,
        cycle_plan=json_value(plan),
        plan_fingerprint=plan.fingerprint,
        plan_admission={"reference": "approval", "fingerprint": plan.fingerprint, "cycle": 1},
        observation_reference="observation:1",
        runtime_metadata={"opaque": ["retained"]},
    )
    repaired, event = _new_cycle(json_value(data), "repair", settings)
    assert event == "repair" and repaired["cycle_plan"] == json_value(plan)
    assert repaired["plan_admission"] == data["plan_admission"]
    assert repaired["plan_fingerprint"] == plan.fingerprint
    assert repaired["observation_reference"] == "observation:1"
    assert repaired["runtime_metadata"] == data["runtime_metadata"]
    fresh, event = _new_cycle(json_value(data), "next_hypothesis", settings)
    assert event == "next_hypothesis" and "cycle_plan" not in fresh
    assert "plan_admission" not in fresh
    assert "plan_fingerprint" not in fresh
    assert "observation_reference" not in fresh
    assert fresh["runtime_metadata"] == data["runtime_metadata"]


def previous_run(**updates):
    return {
        "status": "completed",
        "effects_settled": True,
        "config": {"resource_id": "shop"},
        "retained_source": "accepted-2",
        "learning": [
            {"reference": "learning:1", "learning": "Earlier result"},
            {"reference": "learning:2", "learning": "Selected result"},
        ],
        "research_candidates": [
            {"id": "a", "status": "deferred"},
            {"id": "b", "status": "rejected"},
        ],
        "research_reference": "research:version-2",
        "tasks": [{"transcript": "must never seed this"}],
        **updates,
    }


def seed(previous, continuation=None, **changes):
    return continuation_seed(
        previous,
        continuation or RunContinuation("previous", "accepted-2", ("learning:2",), ("a",)),
        **{
            "previous_run_id": "previous",
            "resource_id": "shop",
            "source_revision": "accepted-2",
            **changes,
        },
    )


def test_continuation_selects_retained_references_without_task_transcripts():
    prior = previous_run()
    result = seed(prior)
    assert result["learning"] == [prior["learning"][1]]
    assert result["research_candidates"] == [prior["research_candidates"][0]]
    assert result["research_reference"] == "research:version-2"
    assert result["continuity"]["previous_run_id"] == "previous"
    assert "tasks" not in result
    result["learning"][0]["learning"] = "changed copy"
    assert prior["learning"][1]["learning"] == "Selected result"


@pytest.mark.parametrize(
    "updates,parameters",
    [
        ({"status": "stopping"}, {}),
        ({"effects_settled": False}, {}),
        ({"retained_source": "stale"}, {}),
        ({"config": {"resource_id": "other-shop"}}, {}),
        ({}, {"source_revision": "stale"}),
        ({}, {"previous_run_id": "different"}),
        ({"learning": []}, {}),
        ({"research_candidates": []}, {}),
        ({"research_reference": ""}, {}),
    ],
)
def test_continuation_rejects_unsettled_unrelated_stale_or_missing_records(updates, parameters):
    with pytest.raises(InvalidEvidence):
        seed(previous_run(**updates), **parameters)


def test_stopped_run_may_carry_explicit_learning_gap():
    stopped = previous_run(
        status="stopped",
        learning=[],
        research_candidates=[],
        learning_unavailable="Research was stopped before findings were accepted",
    )
    result = seed(stopped, RunContinuation("previous", "accepted-2"))
    assert result["learning"] == []
    assert result["learning_unavailable"] == stopped["learning_unavailable"]
    stopped.pop("learning_unavailable")
    with pytest.raises(InvalidEvidence):
        seed(stopped, RunContinuation("previous", "accepted-2"))


@pytest.mark.parametrize(
    "changes",
    [
        {"previous_run_id": ""},
        {"accepted_source": ""},
        {"learning_references": ("duplicate", "duplicate")},
        {"candidate_ids": tuple(str(i) for i in range(33))},
        {"learning_references": ("",)},
    ],
)
def test_continuation_requires_bounded_explicit_unique_selection(changes):
    with pytest.raises(ValueError):
        RunContinuation(**{"previous_run_id": "previous", "accepted_source": "accepted", **changes})


def test_plan_bound_configuration_and_approval_clock_validation(tmp_path):
    settings = bounded_config(tmp_path)
    with pytest.raises(TypeError):
        replace(settings, plan_bounds={})
    with pytest.raises(ValueError):
        replace(settings, plan=replace(settings.plan, metric="unapproved"))
    for field, value in [
        ("metrics", ()),
        ("decision_rules", ("same", "same")),
        ("required_guardrails", ("",)),
        ("max_canary_percent", 101),
        ("max_canary_seconds", 0),
        ("max_monitor_grace_seconds", -1),
        ("min_canary_seconds", 61),
    ]:
        with pytest.raises(ValueError):
            replace(settings.plan_bounds, **{field: value})
    for field in ("no_response_seconds", "validity_seconds"):
        with pytest.raises(ValueError):
            ApprovalPolicy(**{field: 0})


def test_new_stop_after_confirmed_cleanup_has_fresh_delivery_identity():
    data = state(
        Step.DECIDE,
        cleanup_confirmed=True,
        effects_settled=True,
        experiment_zero=True,
        stop_request_id="settled-stop",
        stop_request={"request_id": "settled-stop"},
        stop_delivery={"accepted": True},
        stop_delivery_error="old",
    )
    request_stop(data, "operator", "stop after settlement")
    assert data["settled_stop_request_id"] == "settled-stop"
    assert data["stop_request_id"] != "settled-stop"
    assert not {"stop_request", "stop_delivery", "stop_delivery_error"} & data.keys()
    assert data["cleanup_confirmed"] is False
    assert data["effects_settled"] is False
    assert data["experiment_zero"] is False
    request = data["stop_request_id"]
    request_stop(data, "operator", "same unresolved stop")
    assert data["stop_request_id"] == request
