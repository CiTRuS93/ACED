"""Consequential boundaries of the four-stage lifecycle and immutable contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aced._json import canonical_hash, utc_text
from aced.agents import AgentTask
from aced.models import (
    ApprovalMode,
    ApprovalPolicy,
    ApprovalStatus,
    Authorization,
    AuthorizationError,
    Evidence,
    EvidenceRequest,
    ExperimentPlan,
    Goal,
    Principal,
    ProjectConfig,
    SafetyStatus,
    Step,
    StepConfig,
    StopDelivery,
    StopRequest,
    SystemClock,
    Verification,
    VerificationStatus,
    authorize,
)
from aced.transitions import TransitionError, scope_for, transition
from aced.workflow import InvalidEvidence, complete, request_stop, timestamp

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def config(tmp_path: Path) -> ProjectConfig:
    return ProjectConfig(
        "shop",
        tmp_path,
        "source-0",
        ExperimentPlan(
            "conversion",
            "native-rule",
            "canary",
            "main",
            1,
            10,
            10,
            3,
            40,
            10,
            2,
            ("errors", "latency"),
            2,
            2,
        ),
        required_checks=("test-suite", "build"),
    )


def state(step: Step, **updates: Any) -> dict[str, Any]:
    return {
        "step": step.value,
        "scope": scope_for(step),
        "status": "active",
        "cycle": 1,
        "source_baseline": "source-0",
        "candidate": "source-1",
        "artifact": "artifact-1",
        "checked_candidate": "source-1",
        "checked_artifact": "artifact-1",
        "deployment_id": "deployment-1",
        "delivered": True,
        "learning": [],
        "hypothesis": "A simpler action increases conversion",
        "selected_candidate_id": "idea-1",
        "outcome": "promote",
        "valid_result": True,
        "retained_source": "source-1",
        "canary_zero": True,
        "canary_ended_at": utc_text(NOW),
        **updates,
    }


def product_facts(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return {
        "candidate": "source-1",
        "artifact": "artifact-1",
        "deployment_id": "deployment-1",
        "plan_fingerprint": settings.plan.fingerprint,
        "effects_settled": True,
        "execution_settled": True,
        "zero_confirmed": True,
        **updates,
    }


def candidate(identifier: str = "idea-1", status: str = "selected") -> dict[str, Any]:
    return {
        "id": identifier,
        "claim": "Fewer steps improve conversion",
        "evidence": ["research:1"],
        "assumptions": ["Traffic remains comparable"],
        "expected_learning": "Measure friction",
        "effort": "one change",
        "risk": "reversible",
        "dependencies": [],
        "rationale": "Prioritized by observed friction and low effort",
        "status": status,
        "outcomes": [],
    }


def research(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return product_facts(
        settings,
        **{
            "hypothesis": "A simpler action increases conversion",
            "selected_candidate_id": "idea-1",
            "research_reference": "research:version-1",
            "candidates": [candidate(), candidate("idea-2", "deferred")],
            "plan_authorized": True,
            "plan_authorization_reference": "plan-approval:1",
            "plan_authorization_fingerprint": settings.plan.fingerprint,
            **updates,
        },
    )


def implementation(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return product_facts(
        settings,
        source_baseline="source-0",
        checks=dict.fromkeys(settings.required_checks, True),
        observability={
            "reference": "observability:1",
            "queries": ["logs:version-1"],
            "normal_verified": True,
            "failure_verified": True,
            "missing_data_policy": "Absent signals are unknown; stop after grace",
            "monitoring_instructions": "Read matching identity and error rate",
            "guardrails": settings.plan.guardrails,
        },
        **updates,
    )


def canary(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return product_facts(
        settings,
        **{
            "canary_id": "canary-1",
            "cohort": settings.plan.canary_cohort,
            "allocation_percent": settings.plan.canary_percent,
            "started_at": utc_text(NOW - timedelta(seconds=3)),
            "deadline": utc_text(NOW + timedelta(seconds=37)),
            "ended_at": utc_text(NOW),
            "canary_status": "passed",
            "healthy": True,
            "checks_passed": True,
            "samples": settings.plan.canary_min_samples,
            "deadline_stop_armed": True,
            "serving_candidate": "source-1",
            "ready_before_exposure": True,
            "telemetry_verified": True,
            "canary_excluded": True,
            **updates,
        },
    )


def main(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return product_facts(
        settings,
        **{
            "experiment_id": "main-1",
            "cohort": settings.plan.experiment_cohort,
            "allocation_percent": settings.plan.experiment_percent,
            "started_at": utc_text(NOW),
            "deadline": utc_text(NOW + timedelta(seconds=10)),
            "ended_at": utc_text(NOW + timedelta(seconds=10)),
            "experiment_status": "closed",
            "deadline_stop_armed": True,
            "serving_candidate": "source-1",
            "ready_before_exposure": True,
            "telemetry_verified": True,
            "canary_excluded": True,
            "decision_rule": settings.plan.decision_rule,
            "outcome": "promote",
            "valid": True,
            "readout_reference": "analysis:main-1",
            **updates,
        },
    )


def decision(settings: ProjectConfig, **updates: Any) -> dict[str, Any]:
    return product_facts(
        settings,
        **{
            "disposition": "reverted",
            "accepted_source": "source-0",
            "rollback_confirmed": True,
            "learning": "The treatment did not meet the frozen rule",
            "learning_reference": "learning:1",
            "goal_assessment": "undetermined",
            "assessment_reason": "One inconclusive experiment",
            "next_action": "finish",
            **updates,
        },
    )


def test_identity_configuration_and_frozen_contracts(tmp_path: Path) -> None:
    principal = Principal("operator", frozenset({"run:inspect", "project:shop"}))
    authorize(principal, "run:inspect", "shop")
    for action, project in [("run:advance", "shop"), ("run:inspect", "other")]:
        with pytest.raises(AuthorizationError):
            authorize(principal, action, project)
    authorize(Principal("service", frozenset({"run:*", "project:*"})), "run:stop", "shop")
    with pytest.raises(ValueError):
        Goal("shop", " ")
    assert SystemClock().now().tzinfo is UTC
    original = {"assignment": {"exclude": ["canary"]}}
    settings = config(tmp_path)
    plan = replace(settings.plan, native=original)
    original["assignment"]["exclude"].append("new")
    assert plan.native["assignment"]["exclude"] == ("canary",)
    routes = {Step.IMPLEMENT: StepConfig(agent="alternate", tool_profile="editing")}
    configured = replace(settings, plan=plan, steps=routes)
    routes.clear()
    assert configured.step(Step.IMPLEMENT).agent == "alternate"
    assert configured.step(Step.HYPOTHESIZE) == StepConfig()
    assert configured.resource_id == str(tmp_path.resolve())
    assert configured.fingerprint == canonical_hash(configured.snapshot())
    assert configured.fingerprint != settings.fingerprint
    with pytest.raises(TypeError):
        configured.steps[Step.IMPLEMENT] = StepConfig()
    for changes, error in [
        ({"plan": {}}, TypeError),
        ({"steps": {"implement": StepConfig()}}, TypeError),
        ({"required_checks": ()}, ValueError),
        ({"required_checks": ("x", "x")}, ValueError),
        ({"approvals": {}}, TypeError),
        ({"cleanup_tasks": 0}, ValueError),
    ]:
        with pytest.raises(error):
            replace(settings, **changes)


@pytest.mark.parametrize(
    "change",
    [
        {"canary_cohort": "main"},
        {"canary_percent": True},
        {"canary_percent": 0},
        {"experiment_percent": 101},
        {"experiment_percent": float("nan")},
        {"canary_percent": 11},
        {"canary_min_samples": 0},
        {"experiment_seconds": True},
        {"readout_delay_seconds": -1},
        {"canary_max_seconds": 1},
        {"guardrails": ()},
        {"guardrails": ("",)},
        {"monitor_grace_seconds": -1},
    ],
)
def test_plan_rejects_unsafe_exposure(tmp_path: Path, change: dict) -> None:
    with pytest.raises(ValueError):
        replace(config(tmp_path).plan, **change)


@pytest.mark.parametrize(
    "change", [{"agent": " "}, {"timeout_seconds": 0}, {"max_cost": -1}, {"max_cost": True}]
)
def test_step_limits(change: dict) -> None:
    with pytest.raises(ValueError):
        StepConfig(**change)


def test_host_contracts_are_immutable_and_time_bound(tmp_path: Path) -> None:
    facts = {"checks": {"build": True}}
    evidence = Evidence("checks:42", "digest", frozenset({"checks:read"}))
    verification = Verification(
        VerificationStatus.VERIFIED,
        "task-digest",
        facts,
        (evidence,),
        NOW,
        NOW + timedelta(seconds=10),
    )
    facts["checks"]["build"] = False
    assert verification.facts["checks"]["build"] is True
    with pytest.raises(TypeError):
        verification.facts["checks"]["build"] = False
    for changes, error in [
        ({"valid_until": NOW}, ValueError),
        ({"status": "verified"}, TypeError),
        ({"evidence": ("claim",)}, TypeError),
        ({"observed_at": datetime(2026, 1, 1)}, ValueError),
    ]:
        with pytest.raises(error):
            replace(verification, **changes)
    authorization = Authorization(ApprovalStatus.ALLOWED, "task-digest", "approval:42", NOW)
    with pytest.raises(TypeError):
        replace(authorization, status="allowed")
    safety = SafetyStatus(True, True, NOW, NOW + timedelta(seconds=10), "health:42")
    for changes, error in [
        ({"healthy": 1}, TypeError),
        ({"zero_confirmed": 1}, TypeError),
        ({"exposure_active": 1}, TypeError),
        ({"valid_until": NOW}, ValueError),
    ]:
        with pytest.raises(error):
            replace(safety, **changes)
    assert replace(safety, exposure_end=NOW, last_success_at=NOW).exposure_end == NOW
    task = AgentTask(
        "task",
        "run",
        1,
        "hypothesize",
        1,
        "runner",
        "research",
        {},
        {},
        tmp_path,
        NOW,
        0,
        "research",
    )
    request = EvidenceRequest(task, expected={"candidate": "source-1"})
    assert request.task_fingerprint == task.fingerprint
    assert request.request_id == replace(request).request_id
    assert request.request_id != replace(request, boundary="main_exposure").request_id
    stop = StopRequest(
        "stop-1", "shop", "run", "resource", "operator", ("task",), (task.fingerprint,)
    )
    assert stop.task_ids == ("task",)
    delivery = StopDelivery("stop-1", True, "stop:receipt")
    with pytest.raises(TypeError):
        replace(delivery, accepted=1)


def test_approval_policy_defaults_to_review_and_cannot_grant_on_failure() -> None:
    policy = ApprovalPolicy(
        boundaries={"research": ApprovalMode.PREAUTHORIZED}, approvers=("uid:1",)
    )
    assert policy.mode("research") is ApprovalMode.PREAUTHORIZED
    assert policy.mode("main_exposure") is ApprovalMode.REVIEW
    for changes, error in [
        ({"boundaries": {"unknown": ApprovalMode.REVIEW}}, ValueError),
        ({"boundaries": {"research": "review"}}, TypeError),
        ({"delivery_failure": "allow"}, ValueError),
        ({"no_response": "allow"}, ValueError),
    ]:
        with pytest.raises(error):
            replace(policy, **changes)
    with pytest.raises(ValueError):
        policy.mode("admin")


def test_only_four_stages_and_registered_authority_boundaries() -> None:
    assert {step.value for step in Step} == {"hypothesize", "implement", "experiment", "decide"}
    assert transition(Step.HYPOTHESIZE, "accepted") is Step.IMPLEMENT
    assert transition(Step.IMPLEMENT, "accepted") is Step.EXPERIMENT
    assert scope_for(Step.EXPERIMENT, "main_authorized") == "main_exposure"
    assert scope_for(Step.DECIDE, "disposition_authorized") == "disposition"
    for step, event in [
        (Step.HYPOTHESIZE, "main_authorized"),
        (Step.IMPLEMENT, "finish"),
        (Step.EXPERIMENT, "repair"),
        (Step.DECIDE, "accepted"),
    ]:
        with pytest.raises(TransitionError):
            transition(step, event)
    for step in Step:
        for event in ("hold", "resume", "stop", "waiting", "correction", "observation"):
            assert transition(step, event) is step


def test_research_retains_candidates_and_linked_phase_artifact(tmp_path: Path) -> None:
    settings = config(tmp_path)
    initial = state(Step.HYPOTHESIZE, research_candidates=[candidate("old", "deferred")])
    facts = research(
        settings,
        initiative={
            "id": "initiative:1",
            "phase_id": "phase:1",
            "dependencies": [],
            "continuation_criteria": "Continue if outcome supports phase 2",
        },
    )
    accepted, event = complete(initial, facts, settings, NOW)
    assert event == "accepted" and accepted["step"] == "implement"
    assert {item["id"] for item in accepted["research_candidates"]} == {"old", "idea-1", "idea-2"}
    assert accepted["initiative"]["phase_id"] == "phase:1"
    assert initial["research_candidates"] == [candidate("old", "deferred")]
    for change in [
        {"hypothesis": " "},
        {"plan_fingerprint": "wrong"},
        {"candidates": []},
        {"selected_candidate_id": "absent"},
        {"candidates": [candidate(), candidate()]},
        {"candidates": [{**candidate(), "evidence": []}]},
        {"initiative": {}},
        {"candidates": [{**candidate(), "status": "maybe"}]},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(initial, facts | change, settings, NOW)


def test_implementation_requires_exact_checks_and_observable_paths(tmp_path: Path) -> None:
    settings = config(tmp_path)
    facts = implementation(settings)
    accepted, _ = complete(state(Step.IMPLEMENT), facts, settings, NOW)
    assert accepted["step"] == "experiment" and accepted["scope"] == "preparation_canary"
    assert accepted["observability"]["normal_verified"] is True
    changes = [
        {"source_baseline": "wrong"},
        {"candidate": " "},
        {"checks": {}},
        {"checks": {"test-suite": None, "build": True}},
        {"observability": {}},
        {"observability": facts["observability"] | {"failure_verified": False}},
        {"observability": facts["observability"] | {"guardrails": ["new"]}},
        {"effects_settled": False},
    ]
    for change in changes:
        with pytest.raises(InvalidEvidence):
            complete(state(Step.IMPLEMENT), facts | change, settings, NOW)


@pytest.mark.parametrize(
    "change",
    [
        {"samples": 9},
        {"samples": True},
        {"samples": None},
        {"started_at": None},
        {"started_at": "not-a-date"},
        {"started_at": utc_text(NOW + timedelta(seconds=1))},
        {"cohort": "main"},
        {"allocation_percent": True},
        {"plan_fingerprint": "old"},
        {"deployment_id": "old"},
        {"healthy": False},
        {"checks_passed": False},
        {"zero_confirmed": False},
        {"ended_at": utc_text(NOW - timedelta(seconds=1))},
        {"ended_at": utc_text(NOW + timedelta(seconds=40))},
        {"telemetry_verified": False},
        {"ready_before_exposure": False},
        {"serving_candidate": "old"},
        {"deadline_stop_armed": False},
    ],
)
def test_canary_requires_bounded_observed_window(tmp_path: Path, change: dict) -> None:
    settings = config(tmp_path)
    with pytest.raises(InvalidEvidence):
        complete(state(Step.EXPERIMENT), canary(settings, **change), settings, NOW)


@pytest.mark.parametrize("review_delay", [0, 60, 3600])
def test_late_closed_canary_review_uses_native_window(tmp_path: Path, review_delay: int) -> None:
    settings = config(tmp_path)
    passed, event = complete(
        state(Step.EXPERIMENT), canary(settings), settings, NOW + timedelta(seconds=review_delay)
    )
    assert event == "main_authorized" and passed["scope"] == "main_exposure"
    assert passed["canary_zero"] is True
    assert timestamp(passed["canary_ended_at"]) == NOW


def test_native_deadline_cannot_renew_after_uncertainty(tmp_path: Path) -> None:
    settings = config(tmp_path)
    pending, event = complete(
        state(Step.EXPERIMENT), canary(settings, canary_status="running"), settings, NOW
    )
    assert event == "waiting"
    with pytest.raises(InvalidEvidence, match="changed"):
        complete(
            pending,
            canary(
                settings,
                started_at=utc_text(NOW - timedelta(seconds=4)),
                deadline=utc_text(NOW + timedelta(seconds=36)),
            ),
            settings,
            NOW,
        )
    ready, _ = complete(pending, canary(settings), settings, NOW)
    active, event = complete(ready, main(settings, experiment_status="active"), settings, NOW)
    assert event == "waiting" and active["experiment_id"] == "main-1"
    deadline = NOW + timedelta(seconds=10)
    closure_pending, event = complete(
        active, main(settings, experiment_status="active"), settings, deadline
    )
    assert event == "waiting" and closure_pending["status"] == "active"
    assert closure_pending["experiment_deadline"] == active["experiment_deadline"]
    with pytest.raises(InvalidEvidence, match="changed"):
        complete(
            active,
            main(
                settings,
                started_at=utc_text(NOW + timedelta(seconds=1)),
                deadline=utc_text(NOW + timedelta(seconds=11)),
            ),
            settings,
            deadline,
        )
    for change in [
        {"canary_zero": False},
        {"checked_candidate": "old"},
        {"used_experiment_ids": ["main-1"]},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(ready | change, main(settings), settings, deadline)


def test_main_requires_zero_separation_full_duration_and_mature_readout(tmp_path: Path) -> None:
    settings = config(tmp_path)
    ready = state(Step.EXPERIMENT, scope="main_exposure")
    deadline = NOW + timedelta(seconds=10)
    waiting, event = complete(ready, main(settings), settings, deadline)
    assert event == "waiting" and waiting["experiment_zero"] is True
    assert timestamp(waiting["wake_at"]) == deadline + timedelta(seconds=2)
    for change in [
        {"canary_excluded": False},
        {"cohort": "canary"},
        {"zero_confirmed": False},
        {"ended_at": utc_text(NOW + timedelta(seconds=9))},
        {"valid": "yes"},
        {"outcome": "great"},
        {"decision_rule": "changed"},
        {"experiment_status": "unknown"},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(ready, main(settings, **change), settings, deadline + timedelta(seconds=2))
    done, _ = complete(
        waiting, main(settings, valid=False), settings, deadline + timedelta(seconds=2)
    )
    assert done["step"] == "decide" and done["outcome"] == "inconclusive"
    assert done["valid_result"] is False


def test_unsuccessful_attempt_can_finish_without_inventing_main(tmp_path: Path) -> None:
    settings = config(tmp_path)
    initial = state(Step.IMPLEMENT, delivered=False)
    unsuccessful, event = complete(
        initial,
        product_facts(
            settings, unsuccessful=True, main_started=False, reason="No feasible candidate"
        ),
        settings,
        NOW,
    )
    assert event == "unsuccessful" and unsuccessful["step"] == "decide"
    assert "experiment_id" not in unsuccessful
    finished, event = complete(
        unsuccessful, decision(settings, disposition="unchanged"), settings, NOW
    )
    assert event == "finish" and finished["status"] == "completed"
    assert finished["goal_assessment"] == "undetermined"
    assert finished["learning"][0]["outcome"] == "unsuccessful"
    for change in [{"zero_confirmed": False}, {"main_started": None}, {"main_started": True}]:
        with pytest.raises(InvalidEvidence):
            complete(
                initial,
                product_facts(
                    settings, unsuccessful=True, main_started=False, reason="No feasible candidate"
                )
                | change,
                settings,
                NOW,
            )
    with pytest.raises(InvalidEvidence, match="failed decision"):
        complete(unsuccessful, product_facts(settings, unsuccessful=True), settings, NOW)


def test_promotion_has_separate_authority_and_observation(tmp_path: Path) -> None:
    settings = config(tmp_path)
    initial = state(Step.DECIDE)
    proposal = product_facts(
        settings,
        proposed_disposition="promoted",
        proposal_reference="proposal:1",
        rollback_ready=True,
        independent_stop_ready=True,
    )
    permitted, event = complete(initial, proposal, settings, NOW)
    assert event == "disposition_authorized" and permitted["scope"] == "disposition"
    promoted = decision(
        settings,
        disposition="promoted",
        accepted_source="source-1",
        promotion_confirmed=True,
        rollback_ready=True,
        independent_stop_ready=True,
        promoted_at=utc_text(NOW),
        observation_complete=True,
        healthy=True,
    )
    with pytest.raises(InvalidEvidence, match="authority"):
        complete(initial, promoted, settings, NOW)
    waiting, event = complete(permitted, promoted, settings, NOW)
    assert event == "waiting"
    finished, _ = complete(waiting, promoted, settings, NOW + timedelta(seconds=2))
    assert finished["status"] == "completed" and finished["retained_source"] == "source-1"
    for change in [{"outcome": "inconclusive"}, {"valid_result": False}]:
        with pytest.raises(InvalidEvidence, match="native promote"):
            complete(initial | change, proposal, settings, NOW)
    for change in [
        {"healthy": False},
        {"accepted_source": "unrelated"},
        {"observation_complete": False},
        {"promoted_at": utc_text(NOW + timedelta(seconds=1))},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(waiting, promoted | change, settings, NOW + timedelta(seconds=2))


def test_continuation_preserves_learning_candidates_phases_and_fresh_repair_ids(
    tmp_path: Path,
) -> None:
    settings = config(tmp_path)
    initial = state(
        Step.DECIDE,
        unsuccessful=True,
        outcome="unsuccessful",
        canary_id="old-canary",
        experiment_id="old-main",
        research_candidates=[candidate()],
        initiative={"id": "initiative:1", "phase_id": "phase:1"},
    )
    repaired, event = complete(
        initial, decision(settings, next_action="repair", repair_authorized=True), settings, NOW
    )
    assert event == "repair" and repaired["cycle"] == 2 and repaired["step"] == "implement"
    assert (
        repaired["source_baseline"] == "source-0"
        and repaired["hypothesis"] == initial["hypothesis"]
    )
    assert "candidate" not in repaired and "experiment_id" not in repaired
    assert repaired["used_canary_ids"] == ["old-canary"]
    assert repaired["repair_context"]["candidate"] == "source-1"
    assert repaired["initiative"]["phase_id"] == "phase:1"
    assert repaired["research_candidates"][0]["outcomes"][0]["reference"] == "learning:1"
    next_cycle, event = complete(
        initial, decision(settings, next_action="next_hypothesis"), settings, NOW
    )
    assert event == "next_hypothesis" and next_cycle["step"] == "hypothesize"
    assert "hypothesis" not in next_cycle and "initiative" not in next_cycle
    assert len(next_cycle["research_candidates"]) == 1
    for change in [{"repair_authorized": False}, {"plan_fingerprint": "changed"}]:
        with pytest.raises(InvalidEvidence):
            complete(
                initial,
                decision(settings, next_action="repair", repair_authorized=True) | change,
                settings,
                NOW,
            )
    blocked, event = complete(
        initial | {"cycle": settings.max_cycles},
        decision(settings, next_action="next_hypothesis"),
        settings,
        NOW,
    )
    assert event == "blocked" and blocked["status"] == "active"
    assert "budget" in blocked["blocker"] and len(blocked["learning"]) == 1
    again, _ = complete(blocked, decision(settings, next_action="next_hypothesis"), settings, NOW)
    assert len(again["learning"]) == 1


def test_hold_accepts_verified_progress_without_releasing_hold_and_increment_yields(
    tmp_path: Path,
) -> None:
    settings = config(tmp_path)
    held, _ = complete(
        state(Step.IMPLEMENT, status="held"), implementation(settings), settings, NOW
    )
    assert held["status"] == "held" and held["step"] == "experiment"
    increment = {
        "resume_required": True,
        "execution_settled": True,
        "effects_settled": True,
        "wake_at": utc_text(NOW + timedelta(seconds=5)),
        "reason": "Next tested increment",
    }
    waiting, event = complete(state(Step.IMPLEMENT), increment, settings, NOW)
    assert event == "waiting" and waiting["step"] == "implement"
    with pytest.raises(InvalidEvidence):
        complete(
            state(Step.IMPLEMENT),
            increment | {"wake_at": utc_text(NOW - timedelta(seconds=1))},
            settings,
            NOW,
        )


def test_stopping_requires_protection_execution_effects_and_exact_settlement(
    tmp_path: Path,
) -> None:
    settings = config(tmp_path)
    initial = state(
        Step.EXPERIMENT,
        status="held",
        unresolved_tasks=[{"id": "task-1", "fingerprint": "digest-1"}],
    )
    request_stop(initial, "operator", "Stop requested")
    identifier = initial["stop_request_id"]
    request_stop(initial, "failure", "Must not replace operator intent")
    assert initial["step"] == "experiment" and initial["scope"] == "reconcile"
    assert initial["stop_request_id"] == identifier and initial["stop_cause"] == "operator"
    assert initial["hold_requested"] is True
    facts = product_facts(
        settings,
        stop_request_id=identifier,
        stop_protection_applied=True,
        rollback_confirmed=True,
        accepted_source="source-0",
        learning_unavailable="Agent did not return learning",
        settled_tasks=[{"task_id": "task-1", "task_fingerprint": "digest-1"}],
    )
    for change in [
        {"stop_protection_applied": False},
        {"execution_settled": False},
        {"zero_confirmed": False},
        {"rollback_confirmed": False},
        {"settled_tasks": []},
        {"accepted_source": "other"},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(initial, facts | change, settings, NOW)
    stopped, _ = complete(initial, facts, settings, NOW)
    assert stopped["status"] == "stopped" and stopped["cleanup_confirmed"] is True
    assert stopped["learning_unavailable"]
    failure = state(Step.EXPERIMENT)
    request_stop(failure, "failure", "Sustained monitor failure")
    decided, event = complete(
        failure, facts | {"stop_request_id": failure["stop_request_id"]}, settings, NOW
    )
    assert event == "unsuccessful" and decided["step"] == "decide" and decided["status"] == "active"
    learned, _ = complete(
        initial,
        facts | {"learning": "Stopped safely", "learning_reference": "learning:stop"},
        settings,
        NOW,
    )
    assert learned["learning"][0]["outcome"] == "stopped"


@pytest.mark.parametrize("ended_seconds", [5, 12])
def test_unsuccessful_main_retains_shortened_or_late_actual_window(tmp_path, ended_seconds):
    settings = config(tmp_path)
    facts = main(
        settings,
        unsuccessful=True,
        main_started=True,
        reason="Protection stopped attempt",
        ended_at=utc_text(NOW + timedelta(seconds=ended_seconds)),
    )
    failed, event = complete(
        state(Step.EXPERIMENT, scope="main_exposure"), facts, settings, NOW + timedelta(seconds=20)
    )
    assert event == "unsuccessful"
    assert timestamp(failed["experiment_ended_at"]) == NOW + timedelta(seconds=ended_seconds)
    assert timestamp(failed["experiment_deadline"]) == NOW + timedelta(seconds=10)
    for change in [
        {"ended_at": None},
        {"ended_at": utc_text(NOW - timedelta(seconds=1))},
        {"deadline": utc_text(NOW + timedelta(seconds=11))},
    ]:
        with pytest.raises(InvalidEvidence):
            complete(state(Step.EXPERIMENT), facts | change, settings, NOW + timedelta(seconds=20))


def test_repair_archives_prior_stop_delivery_and_has_fresh_stop_identity(tmp_path):
    settings = config(tmp_path)
    initial = state(
        Step.DECIDE,
        unsuccessful=True,
        stop_request_id="old-stop",
        stop_delivery={"accepted": True},
        stop_delivery_error="previous lost response",
    )
    repaired, _ = complete(
        initial, decision(settings, next_action="repair", repair_authorized=True), settings, NOW
    )
    assert repaired["repair_context"]["stop_request_id"] == "old-stop"
    assert repaired["repair_context"]["stop_delivery"]["accepted"] is True
    assert not {"stop_request_id", "stop_delivery", "stop_delivery_error"} & repaired.keys()
    request_stop(repaired, "operator", "Stop repaired cycle")
    assert repaired["stop_request_id"] != "old-stop"
