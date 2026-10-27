"""Small, immutable host contracts for a durable loop of agent tasks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from ._json import canonical_hash, freeze, json_value, utc_text
from .agents import AgentResult, AgentTask


class Step(StrEnum):
    HYPOTHESIZE = "hypothesize"
    IMPLEMENT = "implement"
    EXPERIMENT = "experiment"
    DECIDE = "decide"


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def _positive(value: int, name: str, *, zero: bool = False) -> None:
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"invalid {name}")


@dataclass(frozen=True)
class Goal:
    project_id: str
    objective: str

    def __post_init__(self) -> None:
        _text(self.project_id, "project_id")
        _text(self.objective, "objective")


@dataclass(frozen=True)
class Principal:
    subject: str
    claims: frozenset[str]

    def __post_init__(self) -> None:
        _text(self.subject, "subject")
        object.__setattr__(self, "claims", frozenset(self.claims))


class IdentityProvider(Protocol):
    async def authenticate(self, context: object) -> Principal: ...


class AuthorizationError(PermissionError):
    pass


def authorize(principal: Principal, action: str, project: str) -> None:
    if not ({action, "run:*"} & principal.claims) or not (
        {f"project:{project}", "project:*"} & principal.claims
    ):
        raise AuthorizationError(f"not authorized for {action} on project {project}")


@dataclass(frozen=True)
class ExperimentPlan:
    """A complete cycle plan; accepted plans are immutable through repair."""

    metric: str
    decision_rule: str
    canary_cohort: str
    experiment_cohort: str
    canary_percent: float
    experiment_percent: float
    canary_min_samples: int
    canary_min_seconds: int
    canary_max_seconds: int
    experiment_seconds: int
    monitor_grace_seconds: int
    guardrails: tuple[str, ...]
    readout_delay_seconds: int = 0
    observation_seconds: int = 0
    native: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("metric", "decision_rule", "canary_cohort", "experiment_cohort"):
            _text(getattr(self, name), name)
        if self.canary_cohort == self.experiment_cohort:
            raise ValueError("canary and experiment cohorts must be separate")
        for name in ("canary_percent", "experiment_percent"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or not 0 < value <= 100:
                raise ValueError(f"invalid {name}")
        if self.canary_percent > self.experiment_percent:
            raise ValueError("canary allocation exceeds experiment allocation")
        for name in (
            "canary_min_samples",
            "canary_min_seconds",
            "canary_max_seconds",
            "experiment_seconds",
        ):
            _positive(getattr(self, name), name)
        for name in ("monitor_grace_seconds", "readout_delay_seconds", "observation_seconds"):
            _positive(getattr(self, name), name, zero=True)
        if self.canary_max_seconds < self.canary_min_seconds:
            raise ValueError("canary maximum precedes minimum")
        if not self.guardrails or any(not isinstance(v, str) or not v for v in self.guardrails):
            raise ValueError("guardrails are required")
        object.__setattr__(self, "guardrails", tuple(self.guardrails))
        object.__setattr__(self, "native", freeze(json_value(self.native)))
        canonical_hash(self)

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self)


@dataclass(frozen=True)
class PlanBounds:
    """Frozen run authority for agent-proposed cycle plans.

    These bounds supplement the host's current authorization of the exact plan;
    they do not authorize native controls or validate statistical procedures.
    """

    metrics: tuple[str, ...]
    decision_rules: tuple[str, ...]
    required_guardrails: tuple[str, ...]
    max_canary_percent: float
    max_experiment_percent: float
    max_canary_seconds: int
    max_experiment_seconds: int
    max_monitor_grace_seconds: int
    min_canary_samples: int = 1
    min_canary_seconds: int = 1
    min_readout_delay_seconds: int = 0
    min_observation_seconds: int = 0

    def __post_init__(self) -> None:
        for name in ("metrics", "decision_rules", "required_guardrails"):
            values = tuple(getattr(self, name))
            if not values or len(set(values)) != len(values):
                raise ValueError(f"{name} must contain unique values")
            for value in values:
                _text(value, name)
            object.__setattr__(self, name, values)
        for name in ("max_canary_percent", "max_experiment_percent"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isfinite(value) or not 0 < value <= 100:
                raise ValueError(f"invalid {name}")
        for name in (
            "max_canary_seconds",
            "max_experiment_seconds",
            "min_canary_samples",
            "min_canary_seconds",
        ):
            _positive(getattr(self, name), name)
        for name in (
            "max_monitor_grace_seconds",
            "min_readout_delay_seconds",
            "min_observation_seconds",
        ):
            _positive(getattr(self, name), name, zero=True)
        if self.min_canary_seconds > self.max_canary_seconds:
            raise ValueError("canary minimum exceeds authorized maximum")

    def admit(self, plan: ExperimentPlan) -> None:
        if plan.metric not in self.metrics or plan.decision_rule not in self.decision_rules:
            raise ValueError("cycle plan metric or decision rule is outside authority")
        if not set(self.required_guardrails).issubset(plan.guardrails):
            raise ValueError("cycle plan omits required guardrails")
        for name, ceiling in (
            ("canary_percent", self.max_canary_percent),
            ("experiment_percent", self.max_experiment_percent),
            ("canary_max_seconds", self.max_canary_seconds),
            ("experiment_seconds", self.max_experiment_seconds),
            ("monitor_grace_seconds", self.max_monitor_grace_seconds),
        ):
            if getattr(plan, name) > ceiling:
                raise ValueError(f"cycle plan exceeds authorized {name}")
        for name, floor in (
            ("canary_min_samples", self.min_canary_samples),
            ("canary_min_seconds", self.min_canary_seconds),
            ("readout_delay_seconds", self.min_readout_delay_seconds),
            ("observation_seconds", self.min_observation_seconds),
        ):
            if getattr(plan, name) < floor:
                raise ValueError(f"cycle plan weakens required {name}")


@dataclass(frozen=True)
class RunContinuation:
    """Selected retained records from one closed run, never arbitrary seed content."""

    previous_run_id: str
    accepted_source: str
    learning_references: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.previous_run_id, "previous_run_id")
        _text(self.accepted_source, "accepted_source")
        for name in ("learning_references", "candidate_ids"):
            values = tuple(getattr(self, name))
            if len(values) > 32 or len(set(values)) != len(values):
                raise ValueError(f"{name} must contain at most 32 unique selections")
            for value in values:
                _text(value, name)
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class StepConfig:
    agent: str | None = None
    instructions: str = ""
    tool_profile: str = "default"
    timeout_seconds: int = 900
    max_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.agent is not None:
            _text(self.agent, "agent")
        _text(self.tool_profile, "tool_profile")
        _positive(self.timeout_seconds, "timeout_seconds")
        if isinstance(self.max_cost, bool) or not isfinite(self.max_cost) or self.max_cost < 0:
            raise ValueError("invalid max_cost")


class ApprovalMode(StrEnum):
    REVIEW = "review"
    DENY = "deny"
    PREAUTHORIZED = "preauthorized"


SCOPES = frozenset(
    {
        "research",
        "implementation",
        "preparation_canary",
        "main_exposure",
        "decision",
        "disposition",
        "correction",
        "reconcile",
    }
)
DEFAULT_CHECKS: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalPolicy:
    """Connection metadata for existing host authority, never a tool permission system.

    Unspecified boundaries require review. The host authenticates approvers and
    applies its current policy on every authorization read.
    """

    boundaries: Mapping[str, ApprovalMode] = field(default_factory=dict)
    approvers: tuple[str, ...] = ()
    channel: str = "local"
    notification_destinations: tuple[str, ...] = ()
    events: tuple[str, ...] = ("approval_requested", "blocked", "stopped", "completed")
    delivery_failure: str = "wait"
    no_response: str = "wait"
    escalation: str = "operator"
    no_response_seconds: int = 300
    validity_seconds: int = 900

    def __post_init__(self) -> None:
        if any(scope not in SCOPES for scope in self.boundaries):
            raise ValueError("unknown approval boundary")
        if any(not isinstance(mode, ApprovalMode) for mode in self.boundaries.values()):
            raise TypeError("approval boundaries require ApprovalMode values")
        for name in ("channel", "escalation"):
            _text(getattr(self, name), name)
        for name in ("no_response_seconds", "validity_seconds"):
            _positive(getattr(self, name), name)
        if self.delivery_failure not in {"wait", "escalate"} or self.no_response not in {
            "wait",
            "escalate",
        }:
            raise ValueError("approval failures must wait or escalate")
        for name in ("approvers", "notification_destinations", "events"):
            values = tuple(getattr(self, name))
            for value in values:
                _text(value, name)
            object.__setattr__(self, name, values)
        object.__setattr__(self, "boundaries", MappingProxyType(dict(self.boundaries)))

    def mode(self, scope: str) -> ApprovalMode:
        if scope not in SCOPES:
            raise ValueError("unknown approval boundary")
        return self.boundaries.get(scope, ApprovalMode.REVIEW)


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    workspace: Path
    source_revision: str
    plan: ExperimentPlan
    default_agent: str = "codex"
    steps: Mapping[Step, StepConfig] = field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    max_tasks: int = 100
    max_attempts: int = 3
    max_cycles: int = 10
    poll_seconds: int = 5
    resource_id: str = ""
    required_checks: tuple[str, ...] = DEFAULT_CHECKS
    cleanup_tasks: int = 3
    approvals: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    plan_bounds: PlanBounds | None = None
    require_research_observation: bool = False

    def __post_init__(self) -> None:
        for name in ("project_id", "source_revision", "default_agent"):
            _text(getattr(self, name), name)
        for name in ("max_tasks", "max_attempts", "max_cycles", "poll_seconds", "cleanup_tasks"):
            _positive(getattr(self, name), name)
        if not isinstance(self.plan, ExperimentPlan):
            raise TypeError("plan must be an ExperimentPlan")
        if type(self.require_research_observation) is not bool:
            raise TypeError("require_research_observation must be a boolean")
        if self.plan_bounds is not None:
            if not isinstance(self.plan_bounds, PlanBounds):
                raise TypeError("plan_bounds must be PlanBounds or None")
            self.plan_bounds.admit(self.plan)
        if any(
            not isinstance(k, Step) or not isinstance(v, StepConfig) for k, v in self.steps.items()
        ):
            raise TypeError("steps must map Step to StepConfig")
        object.__setattr__(self, "workspace", Path(self.workspace).resolve())
        object.__setattr__(self, "resource_id", self.resource_id or str(self.workspace))
        _text(self.resource_id, "resource_id")
        if not self.required_checks or any(
            not isinstance(name, str) or not name.strip() for name in self.required_checks
        ):
            raise ValueError("required checks are required")
        if len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("required checks must be unique")
        if not isinstance(self.approvals, ApprovalPolicy):
            raise TypeError("approvals must be an ApprovalPolicy")
        object.__setattr__(self, "steps", MappingProxyType(dict(self.steps)))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "required_checks", tuple(self.required_checks))

    def step(self, step: Step) -> StepConfig:
        return self.steps.get(step, StepConfig())

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = json_value(self)
        result["workspace"] = str(self.workspace)
        return result

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.snapshot())


class ApprovalStatus(StrEnum):
    ALLOWED = "allowed"
    WAITING = "waiting"
    DENIED = "denied"


@dataclass(frozen=True)
class Authorization:
    status: ApprovalStatus
    task_fingerprint: str
    reference: str
    valid_until: datetime
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ApprovalStatus):
            raise TypeError("invalid approval status")
        _text(self.task_fingerprint, "task fingerprint")
        _text(self.reference, "authorization reference")
        utc_text(self.valid_until)


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    WAITING = "waiting"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    RETRY_SAFE = "retry_safe"


@dataclass(frozen=True)
class EvidenceRequest:
    """An identity-bound read of existing host records, without executing work."""

    task: AgentTask
    result: AgentResult | None = None
    expected: Mapping[str, Any] = field(default_factory=dict)
    purpose: str = "handoff"
    boundary: str = ""

    def __post_init__(self) -> None:
        _text(self.purpose, "evidence purpose")
        object.__setattr__(self, "expected", freeze(json_value(self.expected)))
        canonical_hash(self.expected)

    @property
    def task_fingerprint(self) -> str:
        return self.task.fingerprint

    @property
    def request_id(self) -> str:
        return canonical_hash(
            {
                "task": self.task.fingerprint,
                "expected": self.expected,
                "purpose": self.purpose,
                "boundary": self.boundary,
            }
        )


@dataclass(frozen=True)
class StopRequest:
    """Durable delivery intent; acceptance does not establish effective zero."""

    request_id: str
    project_id: str
    run_id: str
    resource_id: str
    reason: str
    task_ids: tuple[str, ...] = ()
    task_fingerprints: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    expected: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "project_id", "run_id", "resource_id", "reason"):
            _text(getattr(self, name), name)
        for name in ("task_ids", "task_fingerprints", "operations"):
            values = tuple(getattr(self, name))
            for value in values:
                _text(value, name)
            object.__setattr__(self, name, values)
        object.__setattr__(self, "expected", freeze(json_value(self.expected)))
        canonical_hash(self.expected)


@dataclass(frozen=True)
class StopDelivery:
    request_id: str
    accepted: bool
    reference: str
    reason: str = ""

    def __post_init__(self) -> None:
        _text(self.request_id, "stop request_id")
        _text(self.reference, "stop delivery reference")
        if type(self.accepted) is not bool:
            raise TypeError("stop acceptance must be boolean")


@dataclass(frozen=True)
class Evidence:
    reference: str
    digest: str
    read_claims: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _text(self.reference, "evidence reference")
        _text(self.digest, "evidence digest")
        object.__setattr__(self, "read_claims", frozenset(self.read_claims))


@dataclass(frozen=True)
class Verification:
    """Trusted host observation, never constructed from agent JSON unchecked."""

    status: VerificationStatus
    task_fingerprint: str
    facts: Mapping[str, Any]
    evidence: tuple[Evidence, ...]
    observed_at: datetime
    valid_until: datetime
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, VerificationStatus):
            raise TypeError("invalid verification status")
        _text(self.task_fingerprint, "task fingerprint")
        utc_text(self.observed_at)
        utc_text(self.valid_until)
        if self.valid_until <= self.observed_at:
            raise ValueError("verification validity must follow observation")
        if not all(isinstance(e, Evidence) for e in self.evidence):
            raise TypeError("invalid evidence")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "facts", freeze(json_value(self.facts)))
        canonical_hash(self.facts)


@dataclass(frozen=True)
class SafetyStatus:
    """Host operational safety under predefined triggers, separate from business benefit.

    An ambiguous or nonwinning business result alone must not set ``healthy=False``
    or ``stop_required=True``. Independent stopping remains required; the host owns
    safety thresholds and any bounded monitoring grace.
    """

    healthy: bool
    independent_stop_ready: bool
    observed_at: datetime
    valid_until: datetime
    reference: str
    reason: str = ""
    zero_confirmed: bool = False
    exposure_end: datetime | None = None
    exposure_active: bool | None = None
    stop_reason: str | None = None
    degraded: bool = False
    last_success_at: datetime | None = None
    stop_required: bool = False
    protection_applied: bool = False
    experiment_id: str | None = None
    candidate: str | None = None
    plan_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if any(
            type(flag) is not bool
            for flag in (
                self.healthy,
                self.independent_stop_ready,
                self.zero_confirmed,
                self.degraded,
                self.stop_required,
                self.protection_applied,
            )
        ):
            raise TypeError("safety flags must be booleans")
        if self.exposure_active is not None and type(self.exposure_active) is not bool:
            raise TypeError("exposure_active must be boolean or unknown")
        for value in (self.exposure_end, self.last_success_at):
            if value is not None:
                utc_text(value)
        utc_text(self.observed_at)
        utc_text(self.valid_until)
        _text(self.reference, "safety reference")
        if self.valid_until <= self.observed_at:
            raise ValueError("safety validity must follow observation")


class Infrastructure(Protocol):
    """Trusted host bridge to existing authority and independently read evidence."""

    async def authorize(
        self, task: AgentTask, principal: Principal, *, purpose: str = "dispatch"
    ) -> Authorization: ...
    async def read_evidence(
        self, request: EvidenceRequest, principal: Principal
    ) -> Verification: ...
    async def safety(self, project_id: str, run_id: str, principal: Principal) -> SafetyStatus: ...
    async def request_stop(self, request: StopRequest, principal: Principal) -> StopDelivery: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class Inspection:
    id: str
    project_id: str
    key: str
    status: str
    step: Step
    cycle: int
    blocker: str | None
    wake_at: str | None
    data: Mapping[str, Any]
    revision: int
    redacted: bool = False
