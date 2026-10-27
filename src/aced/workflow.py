"""Pure evidence guards for four stages; product procedures stay with agents."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ._json import json_value, utc_text
from .models import DEFAULT_CHECKS, ExperimentPlan, ProjectConfig, RunContinuation, Step
from .transitions import scope_for, transition

CHECKS = DEFAULT_CHECKS
INSTRUCTIONS = {
    Step.HYPOTHESIZE: (
        "Research the goal against accepted source and prior learning using approved tools. "
        "Retain multiple candidates with stable IDs, claims, evidence, assumptions, expected "
        "learning/value, effort, risk, dependencies and selection/defer/rejection rationale in "
        "a versioned artifact or existing tracker. Re-evaluate retained and external proposals; "
        "select one falsifiable hypothesis and propose a complete cycle plan within the frozen "
        "host authority bounds. Obtain exact plan authorization before implementation; a fixed "
        "host plan remains an allowed policy. Preserve actual observations, "
        "denominators, dates/cohorts and references beside claims. Distinguish evidence from "
        "assumptions. Linked phases retain a parent initiative, dependencies and continuation "
        "criteria. Each real experiment is a separate learning cycle; preparatory engineering "
        "does not establish product benefit. Return the selected candidate and artifact reference."
    ),
    Step.IMPLEMENT: (
        "Implement the selected hypothesis from the accepted baseline using existing tools. "
        "Own ordinary editing, test/debug and engineering increments within this stage. Obtain "
        "trusted check records for the exact final candidate/artifact. Reuse or add error, health, "
        "latency and feature instrumentation. Verify normal and failure paths in the authorized "
        "test environment; retain queries, signal references, missing/stale-data interpretation, "
        "monitoring instructions and the frozen guardrails. Raw telemetry stays in native systems. "
        "Repair preserves the hypothesis/plan and baseline; a material change needs a new research "
        "cycle. Do not deploy under implementation authority or modify trusted check records."
    ),
    Step.EXPERIMENT: (
        "Own the experiment procedure through existing tools within the supplied scope. Under "
        "preparation_canary, deploy the checked candidate disabled; verify serving identity, "
        "readiness and useful telemetry before exposure, and arm independent stopping. Operate "
        "one bounded canary; inspect its window and confirm zero. Yield before main_exposure "
        "authority. Main uses a separate population and fixed allocation under its original native "
        "first-allocation deadline. Yield while work/time is pending. After uncertainty inspect "
        "the original operation; never renew or restart exposure. After actual closure obtain the "
        "mature native readout or an explicitly unsuccessful attempt. Missing traffic/telemetry is "
        "not health. Routine monitoring/hard stopping belongs to the deterministic host; diagnose "
        "meaningful anomalies. Keep independent stopping available throughout exposure under "
        "predefined host safety triggers. An ambiguous or nonwinning business result alone is "
        "not an emergency-stop trigger; preserve the planned window and mature readout unless "
        "a safety trigger or authorized stop applies. Operational health does not establish "
        "business benefit."
    ),
    Step.DECIDE: (
        "Interpret the exact readout or unsuccessful attempt and its limitations. Propose an "
        "eligible disposition; yield before a new product effect requires disposition authority. "
        "Use authorized tools to apply/observe it, including delayed-harm checks and separately "
        "authorized rollback. Verify retained source and settled effects. Retain evidence-linked "
        "learning and candidate/phase outcomes. Return goal_assessment attained/not_attained/"
        "undetermined and next_action next_hypothesis/repair/finish with rationale. Repair needs "
        "explicit authority and the same hypothesis/plan with fresh IDs; a changed hypothesis "
        "uses next_hypothesis. Goal attainment is separate from experiment success."
    ),
}


class InvalidEvidence(ValueError):
    pass


def request_stop(data: dict[str, Any], cause: str, reason: str) -> None:
    """Stop is sticky, orthogonal to the stage, and never proof of product closure."""
    transition(Step(data["step"]), "stop")
    closed = data.get("cleanup_confirmed") is True or data.get("experiment_zero") is True
    if closed and data["status"] != "stopping":
        if data.get("stop_request_id"):
            data["settled_stop_request_id"] = data["stop_request_id"]
        for key in ("stop_request_id", "stop_request", "stop_delivery", "stop_delivery_error"):
            data.pop(key, None)
        data.update(cleanup_confirmed=False, effects_settled=False, experiment_zero=False)
    if data["status"] == "held":
        data["hold_requested"] = True
    if data.get("stop_cause") != "operator":
        if data["status"] != "stopping" or cause != "failure":
            data["stop_cause"] = cause
            data["stop_reason"] = reason
    data.setdefault("stop_request_id", str(uuid4()))
    data["status"] = "stopping"
    data["scope"] = "reconcile"
    data["wake_at"] = None


def timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise InvalidEvidence("timestamp is missing")
    try:
        return datetime.fromisoformat(utc_text(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidEvidence("invalid timestamp") from exc


def _require(facts: Mapping[str, Any], name: str, expected: Any = True) -> None:
    value = facts.get(name)
    good = (
        value is expected
        if type(expected) is bool
        else value == expected and type(value) is not bool
    )
    if not good:
        raise InvalidEvidence(f"required evidence does not match: {name}")


def _string(facts: Mapping[str, Any], name: str) -> str:
    value = facts.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidEvidence(f"required evidence is missing: {name}")
    return value


def _strings(facts: Mapping[str, Any], name: str, *, empty: bool = False) -> list[str]:
    values = facts.get(name)
    if not isinstance(values, (tuple, list)) or (not values and not empty):
        raise InvalidEvidence(f"required list is missing: {name}")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise InvalidEvidence(f"invalid list: {name}")
    return list(values)


def _settled(facts: Mapping[str, Any]) -> None:
    _require(facts, "execution_settled")
    _require(facts, "effects_settled")


def _identity(data: dict[str, Any], facts: Mapping[str, Any], config: ProjectConfig) -> None:
    _require(facts, "plan_fingerprint", config.plan.fingerprint)
    for name in ("candidate", "artifact"):
        _require(facts, name, data[name])
    if data.get("deployment_id"):
        _require(facts, "deployment_id", data["deployment_id"])


def _advance(data: dict[str, Any], event: str) -> tuple[dict[str, Any], str]:
    previous = Step(data["step"])
    data["step"] = transition(previous, event).value
    if event in {
        "accepted",
        "main_authorized",
        "disposition_authorized",
        "unsuccessful",
        "next_hypothesis",
        "repair",
    }:
        data["scope"] = scope_for(previous, event)
    data["wake_at"] = None
    data["blocker"] = None
    return data, event


def _wait(data: dict[str, Any], when: datetime) -> tuple[dict[str, Any], str]:
    transition(Step(data["step"]), "waiting")
    data["wake_at"] = utc_text(when)
    return data, "waiting"


def _research(data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig) -> None:
    _settled(facts)
    try:
        plan = ExperimentPlan(**facts["plan"]) if "plan" in facts else config.plan
        if config.plan_bounds is None:
            if plan.fingerprint != config.plan.fingerprint:
                raise ValueError("cycle plan differs from fixed host policy")
        else:
            config.plan_bounds.admit(plan)
    except (TypeError, ValueError) as error:
        raise InvalidEvidence(f"cycle plan admission rejected: {error}") from error
    _require(facts, "plan_fingerprint", plan.fingerprint)
    _require(facts, "plan_authorized")
    _require(facts, "plan_authorization_fingerprint", plan.fingerprint)
    authorization = _string(facts, "plan_authorization_reference")
    if data.get("cycle_plan") and ExperimentPlan(**data["cycle_plan"]) != plan:
        raise InvalidEvidence("accepted cycle plan is immutable")
    data["hypothesis"] = _string(facts, "hypothesis")
    selected = _string(facts, "selected_candidate_id")
    data["research_reference"] = _string(facts, "research_reference")
    candidates = facts.get("candidates")
    if not isinstance(candidates, (list, tuple)) or not candidates:
        raise InvalidEvidence("retained research candidates are required")
    retained = {candidate["id"]: candidate for candidate in data.get("research_candidates", [])}
    seen: set[str] = set()
    selections: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise InvalidEvidence("invalid research candidate")
        identifier = _string(candidate, "id")
        if identifier in seen:
            raise InvalidEvidence("duplicate research candidate ID")
        seen.add(identifier)
        for name in ("claim", "expected_learning", "effort", "risk", "rationale"):
            _string(candidate, name)
        _strings(candidate, "evidence")
        for name in ("assumptions", "dependencies"):
            _strings(candidate, name, empty=True)
        if candidate.get("status") not in {"selected", "deferred", "rejected"}:
            raise InvalidEvidence("invalid research candidate status")
        if candidate["status"] == "selected":
            selections.append(identifier)
        outcomes = candidate.get("outcomes", [])
        if not isinstance(outcomes, (tuple, list)):
            raise InvalidEvidence("invalid research candidate outcomes")
        updated = json_value(candidate)
        previous_outcomes = retained.get(identifier, {}).get("outcomes", [])
        updated["outcomes"] = previous_outcomes + [
            item for item in outcomes if item not in previous_outcomes
        ]
        retained[identifier] = updated
    if selections != [selected]:
        raise InvalidEvidence("exactly the selected candidate must be marked selected")
    for identifier, candidate in retained.items():
        if identifier != selected and candidate.get("status") == "selected":
            candidate["status"] = "deferred"
    initiative = facts.get("initiative")
    if initiative is not None:
        if not isinstance(initiative, Mapping):
            raise InvalidEvidence("invalid initiative artifact")
        for name in ("id", "phase_id", "continuation_criteria"):
            _string(initiative, name)
        _strings(initiative, "dependencies", empty=True)
        data["initiative"] = json_value(initiative)
    else:
        data.pop("initiative", None)
    data["research_candidates"] = list(retained.values())
    data["selected_candidate_id"] = selected
    data["cycle_plan"] = json_value(plan)
    data["plan_fingerprint"] = plan.fingerprint
    data["plan_admission"] = {
        "reference": authorization,
        "fingerprint": plan.fingerprint,
        "cycle": data["cycle"],
    }


def continuation_seed(
    previous: Mapping[str, Any],
    continuation: RunContinuation,
    *,
    previous_run_id: str,
    resource_id: str,
    source_revision: str,
) -> dict[str, Any]:
    """Select only verified closed-run records after the caller authenticates access."""
    if continuation.previous_run_id != previous_run_id:
        raise InvalidEvidence("continuation run identity does not match")
    if previous.get("status") not in {"completed", "stopped"}:
        raise InvalidEvidence("continuation requires a terminal previous run")
    _require(previous, "effects_settled")
    if previous.get("config", {}).get("resource_id") != resource_id:
        raise InvalidEvidence("continuation shared-product resource does not match")
    if previous.get("retained_source") != continuation.accepted_source or (
        source_revision != continuation.accepted_source
    ):
        raise InvalidEvidence("continuation accepted source does not match")
    selected_learning = []
    for reference in continuation.learning_references:
        matches = [
            item for item in previous.get("learning", []) if item.get("reference") == reference
        ]
        if len(matches) != 1:
            raise InvalidEvidence("continuation learning reference is missing or ambiguous")
        selected_learning.append(json_value(matches[0]))
    selected_candidates = []
    for identifier in continuation.candidate_ids:
        matches = [
            item for item in previous.get("research_candidates", []) if item.get("id") == identifier
        ]
        if len(matches) != 1:
            raise InvalidEvidence("continuation candidate is missing or ambiguous")
        selected_candidates.append(json_value(matches[0]))
    result: dict[str, Any] = {
        "continuity": json_value(continuation),
        "learning": selected_learning,
        "research_candidates": selected_candidates,
    }
    if selected_candidates:
        result["research_reference"] = _string(previous, "research_reference")
    if not previous.get("learning"):
        if previous.get("status") != "stopped":
            raise InvalidEvidence("completed previous run is missing retained learning")
        result["learning_unavailable"] = _string(previous, "learning_unavailable")
    return result


def _implementation(data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig) -> None:
    _settled(facts)
    _require(facts, "plan_fingerprint", config.plan.fingerprint)
    _require(facts, "source_baseline", data["source_baseline"])
    candidate = _string(facts, "candidate")
    artifact = _string(facts, "artifact")
    checks = facts.get("checks")
    if not isinstance(checks, Mapping):
        raise InvalidEvidence("trusted checks are required")
    for check in config.required_checks:
        _require(checks, check)
    observability = facts.get("observability")
    if not isinstance(observability, Mapping):
        raise InvalidEvidence("observability handoff is required")
    for name in ("reference", "missing_data_policy", "monitoring_instructions"):
        _string(observability, name)
    _strings(observability, "queries")
    _require(observability, "normal_verified")
    _require(observability, "failure_verified")
    if set(_strings(observability, "guardrails")) != set(config.plan.guardrails):
        raise InvalidEvidence("observability guardrails do not match frozen plan")
    data.update(
        candidate=candidate,
        artifact=artifact,
        checks=json_value(checks),
        observability=json_value(observability),
        checked_candidate=candidate,
        checked_artifact=artifact,
    )
    for name in ("check_reference", "check_invocation_id", "check_task_id"):
        if name in facts:
            data[name] = _string(facts, name)


def _window(
    data: dict[str, Any],
    facts: dict[str, Any],
    config: ProjectConfig,
    now: datetime,
    *,
    canary: bool,
) -> tuple[datetime, datetime]:
    _identity(data, facts, config)
    prefix = "canary" if canary else "experiment"
    identity = _string(facts, f"{prefix}_id")
    if data.get(f"{prefix}_id"):
        _require(facts, f"{prefix}_id", data[f"{prefix}_id"])
    if identity in data.get(f"used_{prefix}_ids", []):
        raise InvalidEvidence(f"reused {prefix} identity")
    started = timestamp(facts.get("started_at"))
    deadline = timestamp(facts.get("deadline"))
    seconds = config.plan.canary_max_seconds if canary else config.plan.experiment_seconds
    if started > now or deadline != started + timedelta(seconds=seconds):
        raise InvalidEvidence("native exposure deadline does not match frozen duration")
    for suffix, value in (("started_at", started), ("deadline", deadline)):
        key = f"{prefix}_{suffix}"
        if data.get(key) and timestamp(data[key]) != value:
            raise InvalidEvidence(f"native {prefix} {suffix} changed")
        data[key] = utc_text(value)
    _require(
        facts, "cohort", config.plan.canary_cohort if canary else config.plan.experiment_cohort
    )
    _require(
        facts,
        "allocation_percent",
        config.plan.canary_percent if canary else config.plan.experiment_percent,
    )
    _require(facts, "deadline_stop_armed")
    _require(facts, "serving_candidate", data["candidate"])
    _require(facts, "ready_before_exposure")
    _require(facts, "telemetry_verified")
    data[f"{prefix}_id"] = identity
    data["deployment_id"] = _string(facts, "deployment_id")
    data["delivered"] = True
    return started, deadline


def _ended(facts: dict[str, Any], started: datetime, deadline: datetime, now: datetime) -> datetime:
    _require(facts, "zero_confirmed")
    _settled(facts)
    ended = timestamp(facts.get("ended_at"))
    if ended < started or ended > now or ended > deadline:
        raise InvalidEvidence("invalid or excessive exposure window")
    return ended


def _unsuccessful(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig, now: datetime
) -> tuple[dict[str, Any], str]:
    _settled(facts)
    _require(facts, "zero_confirmed")
    _require(facts, "unsuccessful")
    if data.get("candidate"):
        _identity(data, facts, config)
    for name in ("canary_id", "experiment_id"):
        if data.get(name):
            _require(facts, name, data[name])
    # Whether main existed must be established by the host, never inferred from omission.
    main_started = facts.get("main_started")
    if type(main_started) is not bool:
        raise InvalidEvidence("main_started must be established")
    if main_started and not (data.get("experiment_id") or facts.get("experiment_id")):
        raise InvalidEvidence("started main identity is missing")
    if main_started:
        data["experiment_id"] = _string(facts, "experiment_id")
        started = timestamp(facts.get("started_at"))
        deadline = timestamp(facts.get("deadline"))
        ended = timestamp(facts.get("ended_at"))
        if started > ended or ended > now:
            raise InvalidEvidence("unsuccessful main has an invalid actual window")
        if deadline != started + timedelta(seconds=config.plan.experiment_seconds):
            raise InvalidEvidence("unsuccessful main native deadline changed")
        for key, value in (("experiment_started_at", started), ("experiment_deadline", deadline)):
            if data.get(key) and timestamp(data[key]) != value:
                raise InvalidEvidence("unsuccessful main native window changed")
            data[key] = utc_text(value)
        data["experiment_ended_at"] = utc_text(ended)
    data.update(
        unsuccessful=True,
        attempt_reason=_string(facts, "reason"),
        outcome="unsuccessful",
        valid_result=False,
        experiment_zero=True,
        main_started=main_started,
        effects_settled=True,
    )
    return _advance(data, "unsuccessful")


def _experiment(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig, now: datetime
) -> tuple[dict[str, Any], str]:
    preparation = data["scope"] == "preparation_canary"
    if data["scope"] not in {"preparation_canary", "main_exposure"}:
        raise InvalidEvidence("invalid experiment scope")
    if data.get("checked_candidate") != data.get("candidate") or data.get(
        "checked_artifact"
    ) != data.get("artifact"):
        raise InvalidEvidence("candidate is not the checked implementation")
    if not preparation:
        if data.get("canary_zero") is not True:
            raise InvalidEvidence("main requires confirmed canary zero")
        _require(facts, "canary_excluded")
    started, deadline = _window(data, facts, config, now, canary=preparation)
    if preparation:
        status = _string(facts, "canary_status")
        if status == "running":
            return _wait(
                data,
                min(deadline, now + timedelta(seconds=config.poll_seconds))
                if now < deadline
                else now + timedelta(seconds=config.poll_seconds),
            )
        if status != "passed":
            raise InvalidEvidence("canary requires verified unsuccessful outcome or pass")
        ended = _ended(facts, started, deadline, now)
        if (ended - started).total_seconds() < config.plan.canary_min_seconds:
            raise InvalidEvidence("canary minimum duration not reached")
        samples = facts.get("samples")
        if type(samples) is not int or samples < config.plan.canary_min_samples:
            raise InvalidEvidence("canary minimum traffic not reached")
        _require(facts, "healthy")
        _require(facts, "checks_passed")
        _require(facts, "canary_excluded")
        data.update(canary_zero=True, canary_ended_at=utc_text(ended))
        return _advance(data, "main_authorized")
    if started < timestamp(data["canary_ended_at"]):
        raise InvalidEvidence("main exposure precedes canary zero")
    status = _string(facts, "experiment_status")
    data["main_started"] = True
    if status == "active":
        # Deadline passage requests closure evidence; poll order is not product failure.
        return _wait(
            data, deadline if now < deadline else now + timedelta(seconds=config.poll_seconds)
        )
    if status != "closed":
        raise InvalidEvidence("main requires closed or verified unsuccessful outcome")
    ended = _ended(facts, started, deadline, now)
    if ended != deadline:
        raise InvalidEvidence("shortened main requires explicit unsuccessful outcome")
    data.update(experiment_zero=True, experiment_ended_at=utc_text(ended))
    mature = ended + timedelta(seconds=config.plan.readout_delay_seconds)
    if now < mature:
        return _wait(data, mature)
    _require(facts, "decision_rule", config.plan.decision_rule)
    if type(facts.get("valid")) is not bool:
        raise InvalidEvidence("readout validity must be known")
    outcome = _string(facts, "outcome")
    if outcome not in {"promote", "revert", "inconclusive"}:
        raise InvalidEvidence("invalid native outcome")
    data.update(
        outcome=outcome if facts["valid"] else "inconclusive",
        valid_result=facts["valid"],
        readout_reference=_string(facts, "readout_reference"),
        effects_settled=True,
    )
    return _advance(data, "accepted")


def _disposition(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig, now: datetime
) -> datetime | None:
    _settled(facts)
    _require(facts, "zero_confirmed")
    disposition = _string(facts, "disposition")
    source = _string(facts, "accepted_source")
    if disposition == "promoted":
        if data.get("outcome") != "promote" or data.get("valid_result") is not True:
            raise InvalidEvidence("promotion requires a valid native promote result")
        if data.get("scope") != "disposition" or data.get("proposed_disposition") != "promoted":
            raise InvalidEvidence("promotion requires disposition authority")
        _identity(data, facts, config)
        _require(facts, "promotion_confirmed")
        _require(facts, "rollback_ready")
        _require(facts, "independent_stop_ready")
        if source != data["candidate"]:
            raise InvalidEvidence("promoted retained source does not match candidate")
        promoted = timestamp(facts.get("promoted_at"))
        if promoted > now or (
            data.get("promoted_at") and timestamp(data["promoted_at"]) != promoted
        ):
            raise InvalidEvidence("promotion time changed or is in the future")
        data["promoted_at"] = utc_text(promoted)
        observation_end = promoted + timedelta(seconds=config.plan.observation_seconds)
        if now < observation_end:
            return observation_end
        _require(facts, "observation_complete")
        _require(facts, "healthy")
    elif disposition in {"reverted", "unchanged"}:
        if source != data["source_baseline"]:
            raise InvalidEvidence("retained source must preserve baseline")
        if data.get("delivered") or disposition == "reverted":
            _require(facts, "rollback_confirmed")
    else:
        raise InvalidEvidence("invalid disposition")
    data.update(disposition=disposition, retained_source=source, effects_settled=True)
    return None


def _new_cycle(
    data: dict[str, Any], action: str, config: ProjectConfig
) -> tuple[dict[str, Any], str]:
    if data["cycle"] >= config.max_cycles:
        data["blocker"] = "cycle budget exhausted; explicit stop or new authorization required"
        transition(Step.DECIDE, "budget_exhausted")
        return data, "blocked"
    prior = {
        name: deepcopy(data[name])
        for name in (
            "cycle",
            "candidate",
            "artifact",
            "canary_id",
            "experiment_id",
            "outcome",
            "attempt_reason",
            "source_baseline",
            "hypothesis",
            "plan_fingerprint",
            "selected_candidate_id",
            "stop_request_id",
            "stop_request",
            "stop_delivery",
            "stop_delivery_error",
        )
        if name in data
    }
    for prefix in ("canary", "experiment"):
        if data.get(f"{prefix}_id"):
            data.setdefault(f"used_{prefix}_ids", []).append(data[f"{prefix}_id"])
    preserved = set()
    if action == "repair":
        preserved = {
            "hypothesis",
            "selected_candidate_id",
            "research_reference",
            "initiative",
            "cycle_plan",
            "plan_admission",
            "plan_fingerprint",
            "observation_reference",
        }
    # Runtime metadata is opaque; clear cycle evidence explicitly rather than dropping keys.
    cycle_keys = {
        "hypothesis",
        "cycle_plan",
        "plan_admission",
        "plan_fingerprint",
        "selected_candidate_id",
        "research_reference",
        "observation_reference",
        "initiative",
        "candidate",
        "artifact",
        "deployment_id",
        "checked_candidate",
        "checked_artifact",
        "checks",
        "check_reference",
        "check_invocation_id",
        "check_task_id",
        "observability",
        "canary_id",
        "experiment_id",
        "canary_started_at",
        "canary_deadline",
        "canary_ended_at",
        "canary_zero",
        "experiment_started_at",
        "experiment_deadline",
        "experiment_ended_at",
        "experiment_zero",
        "main_started",
        "delivered",
        "outcome",
        "valid_result",
        "readout_reference",
        "unsuccessful",
        "attempt_reason",
        "effects_settled",
        "retained_source",
        "disposition",
        "proposed_disposition",
        "disposition_proposal",
        "promoted_at",
        "goal_assessment",
        "assessment_reason",
        "decision_recorded",
        "cleanup_confirmed",
        "stop_cause",
        "stop_reason",
        "learning_unavailable",
        "stop_request_id",
        "settled_stop_request_id",
        "stop_request",
        "stop_delivery",
        "stop_delivery_error",
    }
    baseline = data["retained_source"]
    for key in cycle_keys - preserved:
        data.pop(key, None)
    data.update(cycle=data["cycle"] + 1, source_baseline=baseline, checkpoint={})
    if action == "repair":
        data["repair_context"] = prior
    else:
        data.pop("repair_context", None)
    return _advance(data, action)


def _decision(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig, now: datetime
) -> tuple[dict[str, Any], str]:
    if data["scope"] not in {"decision", "disposition"}:
        raise InvalidEvidence("invalid decision scope")
    if data.get("candidate"):
        _identity(data, facts, config)
    proposal = facts.get("proposed_disposition")
    if proposal is not None and "learning" not in facts:
        _settled(facts)
        _require(facts, "zero_confirmed")
        if data["scope"] != "decision" or proposal not in {"promoted", "reverted"}:
            raise InvalidEvidence("invalid disposition proposal")
        _identity(data, facts, config)
        if proposal == "promoted":
            if data.get("outcome") != "promote" or data.get("valid_result") is not True:
                raise InvalidEvidence("promotion requires a valid native promote result")
            _require(facts, "rollback_ready")
            _require(facts, "independent_stop_ready")
        data["disposition_proposal"] = _string(facts, "proposal_reference")
        data["proposed_disposition"] = proposal
        return _advance(data, "disposition_authorized")
    wait_until = _disposition(data, facts, config, now)
    if wait_until is not None:
        return _wait(data, wait_until)
    learning = _string(facts, "learning")
    learning_reference = _string(facts, "learning_reference")
    assessment = facts.get("goal_assessment")
    if assessment not in {"attained", "not_attained", "undetermined"}:
        raise InvalidEvidence("invalid goal assessment")
    action = facts.get("next_action")
    if action not in {"finish", "next_hypothesis", "repair"}:
        raise InvalidEvidence("invalid continuation action")
    data["assessment_reason"] = _string(facts, "assessment_reason")
    data["goal_assessment"] = assessment
    if action == "repair":
        if not data.get("unsuccessful") or not data.get("hypothesis"):
            raise InvalidEvidence("repair requires an unsuccessful retained hypothesis")
        _require(facts, "repair_authorized")
        _require(facts, "plan_fingerprint", config.plan.fingerprint)
    if not data.get("decision_recorded"):
        record = {
            "cycle": data["cycle"],
            "source": data["retained_source"],
            "learning": learning,
            "reference": learning_reference,
            "outcome": data.get("outcome", "unsuccessful"),
            "assessment": assessment,
            "reason": data["assessment_reason"],
            "action": action,
            "selected_candidate_id": data.get("selected_candidate_id"),
            "experiment_id": data.get("experiment_id"),
            "plan_fingerprint": config.plan.fingerprint,
            "initiative": data.get("initiative"),
        }
        data.setdefault("learning", []).append(record)
        for candidate in data.get("research_candidates", []):
            if candidate["id"] == data.get("selected_candidate_id"):
                candidate.setdefault("outcomes", []).append(
                    {
                        "cycle": data["cycle"],
                        "reference": learning_reference,
                        "experiment_id": data.get("experiment_id"),
                        "outcome": record["outcome"],
                        "plan_fingerprint": config.plan.fingerprint,
                    }
                )
        data["decision_recorded"] = True
    if action == "finish":
        data.update(status="completed", wake_at=None, blocker=None)
        return _advance(data, "finish")
    return _new_cycle(data, action, config)


def _reconcile(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig
) -> tuple[dict[str, Any], str]:
    _settled(facts)
    _require(facts, "zero_confirmed")
    _require(facts, "stop_protection_applied")
    _require(facts, "stop_request_id", data["stop_request_id"])
    _require(facts, "plan_fingerprint", config.plan.fingerprint)
    for name in ("candidate", "artifact", "deployment_id", "canary_id", "experiment_id"):
        if data.get(name):
            _require(facts, name, data[name])
    expected = {
        (item.get("task_id", item.get("id")), item.get("task_fingerprint", item.get("fingerprint")))
        for item in data.get("unresolved_tasks", [])
    }
    if expected:
        settled = facts.get("settled_tasks")
        if not isinstance(settled, (list, tuple)):
            raise InvalidEvidence("unresolved task settlement is missing")
        bindings = {
            (item.get("task_id"), item.get("task_fingerprint"))
            for item in settled
            if isinstance(item, Mapping)
        }
        if None in {value for pair in expected for value in pair} or not expected.issubset(
            bindings
        ):
            raise InvalidEvidence("unresolved task settlement does not match")
    source = _string(facts, "accepted_source")
    if source not in {data["source_baseline"], data.get("retained_source")}:
        raise InvalidEvidence("cleanup retained source is unrelated")
    if data.get("delivered"):
        _require(facts, "rollback_confirmed")
    data.update(
        cleanup_confirmed=True,
        retained_source=source,
        effects_settled=True,
        experiment_zero=True,
        unresolved_tasks=[],
    )
    if data.get("stop_cause") == "failure":
        data.update(
            unsuccessful=True,
            outcome="unsuccessful",
            valid_result=False,
            attempt_reason=data.get("stop_reason", "failed attempt"),
            status="held" if data.get("hold_requested") else "active",
        )
        return _advance(data, "unsuccessful")
    if facts.get("learning"):
        data.setdefault("learning", []).append(
            {
                "cycle": data["cycle"],
                "source": source,
                "learning": _string(facts, "learning"),
                "reference": _string(facts, "learning_reference"),
                "outcome": "stopped",
                "plan_fingerprint": config.plan.fingerprint,
            }
        )
    else:
        data["learning_unavailable"] = _string(facts, "learning_unavailable")
    data.update(status="stopped", wake_at=None, blocker=None)
    return _advance(data, "stopped")


def complete(
    data: dict[str, Any], facts: dict[str, Any], config: ProjectConfig, now: datetime
) -> tuple[dict[str, Any], str]:
    """Accept only verified consequential facts; never interpret untrusted agent prose."""
    utc_text(now)
    result = deepcopy(data)
    step = Step(result["step"])
    if result.get("cycle_plan") and step is not Step.HYPOTHESIZE:
        try:
            config = replace(config, plan=ExperimentPlan(**result["cycle_plan"]))
        except (TypeError, ValueError) as error:
            raise InvalidEvidence("accepted cycle plan no longer matches authority") from error
    if step is not Step.HYPOTHESIZE and "plan" in facts:
        try:
            observed_plan = ExperimentPlan(**facts["plan"])
        except (TypeError, ValueError) as error:
            raise InvalidEvidence("invalid plan in stage evidence") from error
        if observed_plan.fingerprint != config.plan.fingerprint:
            raise InvalidEvidence("accepted cycle plan cannot change within a cycle")
    result.setdefault("scope", scope_for(step))
    if result.get("status") == "stopping":
        return _reconcile(result, facts, config)
    if facts.get("resume_required") is True:
        _settled(facts)
        when = timestamp(facts.get("wake_at"))
        if when < now:
            raise InvalidEvidence("resume wake time is in the past")
        result["resume_reason"] = _string(facts, "reason")
        return _wait(result, when)
    if facts.get("unsuccessful") is True:
        if step is Step.DECIDE:
            raise InvalidEvidence("failed decision requires correction or intervention")
        return _unsuccessful(result, facts, config, now)
    if step is Step.HYPOTHESIZE:
        _research(result, facts, config)
        return _advance(result, "accepted")
    if step is Step.IMPLEMENT:
        _implementation(result, facts, config)
        return _advance(result, "accepted")
    if step is Step.EXPERIMENT:
        return _experiment(result, facts, config, now)
    return _decision(result, facts, config, now)
