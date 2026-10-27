"""One principal-bound coordinator; procedures and external effects remain host-owned."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from ._json import canonical_hash, freeze, json_value, utc_text
from .agents import AgentResult, AgentRunner, AgentStatus, AgentTask, ExecutionRef
from .models import (
    ApprovalMode,
    ApprovalPolicy,
    ApprovalStatus,
    Authorization,
    Clock,
    EvidenceRequest,
    ExperimentPlan,
    Goal,
    IdentityProvider,
    Infrastructure,
    Inspection,
    PlanBounds,
    Principal,
    ProjectConfig,
    RunContinuation,
    SafetyStatus,
    Step,
    StopRequest,
    SystemClock,
    Verification,
    VerificationStatus,
    authorize,
)
from .store import ConflictError, Lease, Record, SQLiteStore
from .transitions import transition
from .workflow import (
    INSTRUCTIONS,
    InvalidEvidence,
    complete,
    continuation_seed,
    request_stop,
    timestamp,
)

_TERMINAL = {"completed", "stopped"}
_ENDED = {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED, AgentStatus.ABSENT}
_T = TypeVar("_T")
_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["completed", "waiting", "blocked", "failed"]},
        "summary": {"type": "string"},
        "deliverable": {"type": "object"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "operations": {"type": "array", "items": {"type": "string"}},
        "checkpoint": {"type": "object"},
        "wait": {"type": ["object", "null"]},
        "blocker": {"type": ["object", "null"]},
    },
    "required": [
        "outcome",
        "summary",
        "deliverable",
        "evidence",
        "operations",
        "checkpoint",
        "wait",
        "blocker",
    ],
    "additionalProperties": False,
}


def _task(payload: Mapping[str, Any]) -> AgentTask:
    return AgentTask(
        **{
            **payload,
            "workspace": Path(payload["workspace"]),
            "deadline": timestamp(payload["deadline"]),
        }
    )


def _result(payload: Mapping[str, Any]) -> AgentResult:
    execution = payload.get("execution")
    return AgentResult(
        AgentStatus(payload["status"]),
        payload.get("output", {}),
        ExecutionRef(**execution) if execution else None,
        payload.get("reason", ""),
        payload.get("usage"),
    )


def _authorized(approval: Authorization, task: AgentTask, now: datetime) -> bool:
    return (
        approval.status is ApprovalStatus.ALLOWED
        and approval.task_fingerprint == task.fingerprint
        and now < approval.valid_until
    )


def _envelope(result: AgentResult) -> str | None:
    """Validate the small vendor-neutral envelope independently of runner validation."""
    try:
        output = result.output
        if set(output) != set(_OUTPUT_SCHEMA["required"]):
            return "result must contain exactly the documented envelope fields"
        if not isinstance(output["summary"], str) or not output["summary"].strip():
            return "result summary is required"
        for name in ("deliverable", "checkpoint"):
            if not isinstance(output[name], Mapping):
                return f"{name} must be an object"
        for name in ("evidence", "operations"):
            if not isinstance(output[name], (list, tuple)) or any(
                not isinstance(item, str) or not item for item in output[name]
            ):
                return f"{name} must contain references"
        outcome = result.output["outcome"]
        if outcome not in {"completed", "waiting", "blocked", "failed"}:
            return "unknown agent outcome"
        if outcome == "waiting":
            wait = result.output["wait"]
            if not isinstance(wait, Mapping) or wait.get("reason") not in {
                "timer",
                "native_record",
                "authority_boundary",
            }:
                return "waiting requires a named timer, native record or authority boundary"
            if wait["reason"] == "native_record" and not wait.get("reference"):
                return "waiting requires a native record reference"
            if wait["reason"] == "timer":
                timestamp(wait.get("not_before"))
            if wait["reason"] == "authority_boundary" and wait.get("boundary") not in {
                "main_exposure",
                "disposition",
            }:
                return "unsupported authority boundary"
        if outcome in {"blocked", "failed"}:
            blocker = result.output["blocker"]
            if (
                not isinstance(blocker, Mapping)
                or not blocker.get("reason")
                or not blocker.get("owner")
            ):
                return "blocked/failed output requires a reason and responsible owner"
    except (ValueError, TypeError, KeyError) as error:
        return f"invalid result envelope: {type(error).__name__}"
    return None


class Runtime:
    """Owns SQLite lifetime. The host explicitly starts and supervises run_worker."""

    def __init__(
        self,
        database: str | Path,
        *,
        projects: Mapping[str, ProjectConfig],
        runners: Mapping[str, AgentRunner],
        infrastructure: Infrastructure,
        identity_provider: IdentityProvider,
        auth_context: object,
        clock: Clock | None = None,
        profile: str = "development",
        lease_seconds: int = 60,
        host_timeout_seconds: float = 30,
    ) -> None:
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        if host_timeout_seconds <= 0 or host_timeout_seconds >= lease_seconds:
            raise ValueError("host timeout must be positive and shorter than the worker lease")
        if profile != "development":
            raise ValueError("only development is qualified by this preview")
        if any(k != v.project_id for k, v in projects.items()):
            raise ValueError("project registration identity mismatch")
        for config in projects.values():
            names = {config.default_agent, *(s.agent for s in config.steps.values() if s.agent)}
            if not names.issubset(runners):
                raise ValueError("project references an unregistered agent")
        self.store = SQLiteStore(database)
        self.projects = dict(projects)
        self.runners = dict(runners)
        self.infrastructure = infrastructure
        self.identity = identity_provider
        self.auth_context = auth_context
        self.clock = clock or SystemClock()
        self.owner = str(uuid4())
        self.lease_seconds = lease_seconds
        self.host_timeout_seconds = host_timeout_seconds

    async def __aenter__(self) -> Runtime:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Host must join workers first. Closing a runtime never stops product exposure."""
        await self.store.close()

    async def _call(self, work: Awaitable[_T]) -> _T:
        return await asyncio.wait_for(work, self.host_timeout_seconds)

    async def _principal(
        self, action: str, project: str, claims: set[str] | None = None
    ) -> Principal:
        principal = await self._call(self.identity.authenticate(self.auth_context))
        authorize(principal, action, project)
        if claims and not claims.issubset(principal.claims):
            from .models import AuthorizationError

            raise AuthorizationError("required evidence claims are missing")
        return principal

    async def start(
        self, goal: Goal, *, key: str, continuation: RunContinuation | None = None
    ) -> Inspection:
        if not key or key.strip() != key:
            raise ValueError("a trimmed run key is required")
        config = self.projects[goal.project_id]
        principal = await self._principal("run:create", goal.project_id)
        fingerprint = canonical_hash(goal)
        existing = await self.store.find(goal.project_id, key)
        if existing:
            if existing.fingerprint != fingerprint:
                raise ConflictError("named run has a different goal")
            if continuation is not None and existing.data.get("continuity") != json_value(
                continuation
            ):
                raise ConflictError("named run has a different continuity handoff")
            return await self.inspect(existing.id)
        seed: dict[str, Any] = {}
        if continuation is not None:
            if not isinstance(continuation, RunContinuation):
                raise TypeError("continuation must be a RunContinuation")
            previous = await self.store.get(continuation.previous_run_id)
            await self._principal(
                "run:inspect", previous.project_id, set(previous.data["read_claims"])
            )
            seed = continuation_seed(
                previous.data,
                continuation,
                previous_run_id=previous.id,
                resource_id=config.resource_id,
                source_revision=config.source_revision,
            )
            seed["continuity_source"] = {
                "run_id": previous.id,
                "project_id": previous.project_id,
                "revision": previous.revision,
                "fingerprint": previous.fingerprint,
                "data_digest": canonical_hash(previous.data),
            }
            seed["read_claims"] = list(previous.data["read_claims"])
        now, run_id = self.clock.now(), str(uuid4())
        data: dict[str, Any] = {
            "status": "active",
            "step": Step.HYPOTHESIZE.value,
            "scope": "research",
            "cycle": 1,
            "goal": json_value(goal),
            "config": config.snapshot(),
            "current": None,
            "task_count": 0,
            "reserved_tasks": 0,
            "cleanup_count": 0,
            "cleanup_reserved": 0,
            "corrections": 0,
            "attempt": 0,
            "learning": [],
            "read_claims": [],
            "source_baseline": config.source_revision,
            "blocker": None,
            "wake_at": utc_text(now),
            "created_by": principal.subject,
            "canary_id": f"{run_id}:1:canary",
            "experiment_id": f"{run_id}:1:experiment",
            "cycle_started_at": utc_text(now),
            **seed,
        }
        record = await self.store.create(run_id, goal.project_id, key, fingerprint, data)
        return await self.inspect(record.id)

    async def list_runs(
        self, project_id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[tuple[int, Inspection], ...]:
        """Authorized discovery with exclusive creation-event cursors and normal redaction."""
        await self._principal("run:inspect", project_id)
        page = await self.store.list_runs(project_id, limit=limit, after=after)
        return tuple([(seq, await self.inspect(run_id)) for seq, run_id in page])

    async def inspect(self, run_id: str) -> Inspection:
        record = await self.store.get(run_id)
        principal = await self._principal("run:inspect", record.project_id)
        data = record.data
        redacted = not set(data.get("read_claims", [])).issubset(principal.claims)
        visible = {} if redacted else json_value(data)
        if visible.get("task"):
            visible["task"].pop("result", None)
            visible["task"].pop("interruption_result", None)
        return Inspection(
            record.id,
            record.project_id,
            record.key,
            data["status"],
            Step(data["step"]),
            data["cycle"],
            "restricted evidence" if redacted else data.get("blocker"),
            data.get("wake_at"),
            freeze(visible),
            record.revision,
            redacted,
        )

    async def history(
        self, run_id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[dict[str, Any], ...]:
        record = await self.store.get(run_id)
        await self._principal("run:inspect", record.project_id, set(record.data["read_claims"]))
        return tuple(await self.store.history(run_id, limit=limit, after=after))

    async def tasks(
        self, run_id: str, *, limit: int = 100, after: int = 0
    ) -> tuple[dict[str, Any], ...]:
        record = await self.store.get(run_id)
        await self._principal("run:inspect", record.project_id, set(record.data["read_claims"]))
        return tuple(await self.store.tasks(run_id, limit=limit, after=after))

    async def hold(self, run_id: str) -> Inspection:
        return await self._control(run_id, "hold")

    async def resume(self, run_id: str) -> Inspection:
        return await self._control(run_id, "resume")

    async def stop(self, run_id: str) -> Inspection:
        return await self._control(run_id, "stop")

    async def repropose(self, run_id: str) -> Inspection:
        """Replace an unlaunched proposal; it must obtain a new approval."""
        record = await self.store.get(run_id)
        principal = await self._principal("run:repropose", record.project_id)
        data = json_value(record.data)
        if not data.get("current") or data["task"]["status"] != "prepared":
            raise ValueError("only an unlaunched proposal can be replaced")
        transition(Step(data["step"]), "reproposed")
        data["task"]["status"] = "cancelled"
        counter = (
            "cleanup_reserved"
            if data["task"]["task"]["purpose"] == "reconcile"
            else "reserved_tasks"
        )
        if data["task"].get("reservation_held", True):
            data[counter] -= 1
            data["task"]["reservation_held"] = False
        data["current"] = None
        data["blocker"] = None
        data["wake_at"] = utc_text(self.clock.now())
        await self.store.save(record, data, "reproposed", principal.subject, self.clock.now())
        return await self.inspect(run_id)

    async def _safety(self, record: Record, principal: Principal | None = None) -> SafetyStatus:
        if principal is None:
            principal = await self._principal(
                "run:advance", record.project_id, set(record.data["read_claims"])
            )
        return await self._call(self.infrastructure.safety(record.project_id, record.id, principal))

    async def _control(self, run_id: str, operation: str) -> Inspection:
        record = await self.store.get(run_id)
        principal = await self._principal(f"run:{operation}", record.project_id)
        data = json_value(record.data)
        if data["status"] in _TERMINAL:
            return await self.inspect(run_id)
        transition(Step(data["step"]), operation)
        if operation == "hold":
            data["hold_requested"] = True
            if data["status"] == "active":
                data["status"] = "held"
        elif operation == "resume":
            if data["status"] != "held" and not data.get("hold_requested"):
                raise ValueError("only a held run can resume")
            safety = await self._safety(record, principal)
            now = self.clock.now()
            current = data.get("task", {}).get("task", {}) if data.get("current") else {}
            settled_diagnosis = (
                data.get("cleanup_confirmed") is True
                and data.get("effects_settled") is True
                and data.get("experiment_zero") is True
                and data["step"] == Step.DECIDE.value
                and data["scope"] == "decision"
                and current.get("scope")
                not in {"preparation_canary", "main_exposure", "disposition"}
                and safety.zero_confirmed
                and safety.exposure_active is False
                and safety.independent_stop_ready
                and safety.observed_at <= now < safety.valid_until
            )
            if not self._fresh_safe(safety) and not settled_diagnosis:
                raise ValueError("fresh safe infrastructure status required")
            data["hold_requested"] = False
            if data["status"] == "held":
                data["status"] = "active"
        else:
            request_stop(data, "operator", "operator requested stop")
            self._stop_request(record, data)
        data["wake_at"] = utc_text(self.clock.now())
        record = await self.store.save(record, data, operation, principal.subject, self.clock.now())
        # Deliver now, before cancellation, even if ordinary scheduling is held.
        if operation == "stop":
            await self._deliver_stop(record, data, principal)
            try:
                await self.store.save(
                    record, data, "stop_delivery", principal.subject, self.clock.now()
                )
            except ConflictError:
                pass  # Recovery safely redelivers the same immutable request.
            if {"run:advance", "run:*"} & principal.claims and set(data["read_claims"]).issubset(
                principal.claims
            ):
                await self.advance(run_id)
        return await self.inspect(run_id)

    async def record_observation(self, run_id: str, reference: str) -> Inspection:
        if not reference.strip():
            raise ValueError("observation reference required")
        record = await self.store.get(run_id)
        principal = await self._principal("run:observe", record.project_id)
        if (
            record.data.get("observation_reference") == reference
            or record.data["status"] in _TERMINAL
        ):
            return await self.inspect(run_id)
        transition(Step(record.data["step"]), "observation")
        data = {
            **record.data,
            "observation_reference": reference,
            "wake_at": utc_text(self.clock.now()),
        }
        await self.store.save(record, data, "observation", principal.subject, self.clock.now())
        return await self.inspect(run_id)

    async def advance(self, run_id: str) -> Inspection:
        record = await self.store.get(run_id)
        await self._principal("run:advance", record.project_id, set(record.data["read_claims"]))
        if record.data["status"] in _TERMINAL:
            return await self.inspect(run_id)
        lease = await self.store.acquire(
            run_id, self.owner, self.clock.now(), seconds=self.lease_seconds
        )
        if lease is None:
            return await self.inspect(run_id)
        try:
            await self._advance(await self.store.get(run_id), lease)
        finally:
            await self.store.release(lease)
        return await self.inspect(run_id)

    async def _save(self, record: Record, data: dict[str, Any], event: str, lease: Lease) -> Record:
        expected = transition(Step(record.data["step"]), event.rsplit(":", 1)[-1])
        if expected != data["step"]:
            raise ValueError("state change does not match transition registry")
        principal = await self._principal(
            "run:advance", record.project_id, set(data["read_claims"])
        )
        return await self.store.save(
            record, data, event, principal.subject, self.clock.now(), lease
        )

    async def _wait(
        self,
        record: Record,
        data: dict[str, Any],
        reason: str,
        lease: Lease,
        *,
        wake_at: str | None = None,
    ) -> None:
        reason = reason[:500]
        comparison = json_value(data)
        previous = record.data.get("task", {}).get("authorization")
        current = comparison.get("task", {}).get("authorization")
        if previous and current and {**current, "valid_until": previous["valid_until"]} == previous:
            comparison["task"]["authorization"] = previous
            data["task"]["authorization"] = previous
        comparison["blocker"] = reason
        comparison["wake_at"] = record.data.get("wake_at")
        if comparison == record.data:
            return
        data["blocker"] = reason
        data["wake_at"] = wake_at or utc_text(
            self.clock.now() + timedelta(seconds=self._frozen_config(record).poll_seconds)
        )
        await self._save(record, data, "waiting", lease)

    def _frozen_config(self, record: Record) -> ProjectConfig:
        saved = record.data["config"]
        return replace(
            self.projects[record.project_id],
            plan=ExperimentPlan(**record.data.get("cycle_plan", saved["plan"])),
            plan_bounds=PlanBounds(**saved["plan_bounds"]) if saved.get("plan_bounds") else None,
            constraints=tuple(saved["constraints"]),
            max_tasks=saved["max_tasks"],
            max_attempts=saved["max_attempts"],
            max_cycles=saved["max_cycles"],
            workspace=Path(saved["workspace"]),
            source_revision=saved["source_revision"],
            poll_seconds=saved["poll_seconds"],
            resource_id=saved["resource_id"],
            required_checks=tuple(saved["required_checks"]),
            require_research_observation=saved.get(
                "require_research_observation",
                self.projects[record.project_id].require_research_observation,
            ),
            cleanup_tasks=saved["cleanup_tasks"],
            approvals=ApprovalPolicy(
                **{
                    **saved["approvals"],
                    "boundaries": {
                        scope: ApprovalMode(mode)
                        for scope, mode in saved["approvals"]["boundaries"].items()
                    },
                }
            ),
        )

    def _fresh_safe(self, safety: SafetyStatus) -> bool:
        now = self.clock.now()
        return (
            safety.healthy
            and safety.independent_stop_ready
            and safety.observed_at <= now < safety.valid_until
            and not safety.stop_required
        )

    async def _advance(self, record: Record, lease: Lease) -> None:
        data = json_value(record.data)
        now, config = self.clock.now(), self._frozen_config(record)
        try:
            safety = await self._safety(record)
        except Exception as error:
            safety = None
            diagnostic = (
                f"safety unavailable: {type(error).__name__}; consult protected host diagnostics"
            )
        else:
            assert safety is not None
            diagnostic = safety.reason or "fresh safety evidence unavailable"
        active_task = data.get("task", {})
        effectful_task = (
            data.get("current")
            and active_task.get("status") != "prepared"
            and active_task.get("task", {}).get("purpose") != "reconcile"
            and active_task.get("task", {}).get("scope")
            in {"preparation_canary", "main_exposure", "disposition"}
        )
        settled = (
            data.get("cleanup_confirmed")
            and data.get("effects_settled")
            and data.get("experiment_zero")
        )
        # Delivery and an incident remain historical evidence after verified
        # settlement. They cannot create the same stop obligation indefinitely.
        # Read-only diagnosis may proceed; any new capable invocation or observed
        # exposure restores the obligation before further work is accepted.
        exposed = (
            effectful_task
            or (data.get("delivered") and not settled)
            or (safety is not None and safety.exposure_active is True)
        )
        main_scope = data.get("scope") in {"main_exposure", "decision", "disposition"}
        deadline = data.get("experiment_deadline" if main_scope else "canary_deadline")
        # Recovery may see the native deadline before an activation handoff was
        # committed. This observation must identify the original operation.
        if (
            deadline is None
            and safety is not None
            and safety.exposure_end is not None
            and safety.experiment_id == data.get("experiment_id" if main_scope else "canary_id")
            and safety.candidate == data.get("candidate")
            and safety.plan_fingerprint == config.plan.fingerprint
        ):
            deadline = utc_text(safety.exposure_end)
        expected_expiry = bool(deadline and now >= timestamp(deadline))
        closure_overdue = bool(
            deadline
            and now >= timestamp(deadline) + timedelta(seconds=config.plan.monitor_grace_seconds)
        )
        incident = safety is not None and (
            safety.stop_required
            or (
                not safety.healthy
                and not safety.degraded
                and not (expected_expiry and safety.stop_reason == "normal_expiry")
            )
        )
        if safety is not None and safety.exposure_active:
            authorized_promotion = (
                effectful_task
                and active_task.get("task", {}).get("scope") == "disposition"
                and data.get("proposed_disposition") == "promoted"
                and active_task.get("task", {}).get("context", {}).get("proposed_disposition")
                == "promoted"
            )
            reopened = safety.observed_at <= now < safety.valid_until and (
                settled or (data.get("experiment_zero") and not authorized_promotion)
            )
            overdue = closure_overdue and not authorized_promotion
            if reopened:
                diagnostic = "positive exposure observed after confirmed settlement"
            elif overdue and not incident:
                diagnostic = "positive exposure observed beyond native deadline and closure grace"
            incident = (
                bool(reopened or overdue)
                or incident
                or any(
                    actual is not None and expected is not None and actual != expected
                    for actual, expected in (
                        (safety.candidate, data.get("candidate")),
                        (safety.plan_fingerprint, config.plan.fingerprint),
                        (
                            safety.experiment_id,
                            data.get("experiment_id" if main_scope else "canary_id"),
                        ),
                    )
                )
            )
        degraded_within_grace = bool(
            safety is not None
            and safety.degraded
            and safety.independent_stop_ready
            and safety.last_success_at is not None
            and safety.last_success_at <= now
            and now < safety.last_success_at + timedelta(seconds=config.plan.monitor_grace_seconds)
        )
        if exposed and data["status"] != "stopping":
            safe = safety is not None and (
                self._fresh_safe(safety)
                or (
                    safety.zero_confirmed
                    and safety.stop_reason == "normal_expiry"
                    and safety.independent_stop_ready
                    and safety.observed_at <= now < safety.valid_until
                )
            )
            # Expiry changes the obligation to observing native closure. It does
            # not turn a deadline-capped monitor record into evidence of failure.
            if incident or (
                not safe and not degraded_within_grace and (not expected_expiry or closure_overdue)
            ):
                request_stop(data, "failure", diagnostic)
                record = await self._save(record, data, "stop_required", lease)
        if data["status"] == "stopping":
            await self._stopping(record, data, lease)
            return
        if data.get("current"):
            if (
                data["task"]["status"] == "waiting"
                and data.get("wake_at")
                and timestamp(data["wake_at"]) > now
            ):
                return
            await self._process(record, data, lease)
            return
        if data["status"] == "held" or data.get("hold_requested"):
            await self._wait(record, data, "scheduling held; independent safety continues", lease)
            return
        if data.get("wake_at") and timestamp(data["wake_at"]) > now:
            return
        if data["reserved_tasks"] >= config.max_tasks:
            await self._wait(
                record, data, "invocation budget exhausted; operator decision required", lease
            )
            return
        if data.get("corrections", 0) >= config.max_attempts:
            await self._wait(
                record, data, "correction limit exhausted; operator intervention required", lease
            )
            return
        if data["scope"] in {"preparation_canary", "main_exposure", "disposition"} and (
            safety is None or not self._fresh_safe(safety)
        ):
            await self._wait(record, data, diagnostic, lease)
            return
        await self._prepare(record, data, lease)

    async def _prepare(
        self, record: Record, data: dict[str, Any], lease: Lease, *, reconcile: bool = False
    ) -> None:
        config = self._frozen_config(record)
        if (
            not reconcile
            and data["step"] == Step.HYPOTHESIZE.value
            and config.require_research_observation
            and not data.get("observation_reference")
        ):
            await self._wait(
                record,
                data,
                "required research observation missing; capture and record a scoped observation "
                "before Hypothesize inputs freeze",
                lease,
            )
            return
        setting = config.step(Step(data["step"]))
        selected = (
            "goal",
            "cycle",
            "source_baseline",
            "continuity",
            "continuity_source",
            "learning_unavailable",
            "hypothesis",
            "selected_candidate_id",
            "research",
            "research_candidates",
            "research_reference",
            "observation_reference",
            "initiative",
            "candidate",
            "artifact",
            "checks",
            "check_reference",
            "check_invocation_id",
            "check_task_id",
            "delivered",
            "deployment_id",
            "canary_id",
            "experiment_id",
            "cycle_started_at",
            "canary_started_at",
            "canary_deadline",
            "experiment_started_at",
            "experiment_deadline",
            "observability",
            "outcome",
            "attempt_outcome",
            "retained_source",
            "learning",
            "repair_context",
            "checkpoint",
            "unresolved_tasks",
            "stop_reason",
            "stop_request_id",
            "proposed_disposition",
            "disposition_proposal",
            "valid_result",
            "unsuccessful",
            "canary_ended_at",
            "retry_feedback",
            "last_evidence",
        )
        context = {name: data[name] for name in selected if name in data}
        context.update(
            plan=json_value(config.plan),
            plan_template=data["config"]["plan"],
            plan_bounds=data["config"].get("plan_bounds"),
            constraints=data["config"]["constraints"],
            required_checks=data["config"]["required_checks"],
            require_research_observation=config.require_research_observation,
            resource_id=config.resource_id,
            scope=data["scope"],
            original_scope=data["scope"],
            remaining_tasks=config.max_tasks - data["reserved_tasks"],
            approval_policy=data["config"]["approvals"],
        )
        purpose = "reconcile" if reconcile else "work"
        scope = (
            "reconcile"
            if reconcile
            else "correction"
            if data.get("retry_feedback")
            else data["scope"]
        )
        instructions = INSTRUCTIONS[Step(data["step"])]
        if reconcile:
            instructions = (
                "Reconcile the original tasks and native operations in context. Inspect actual "
                "state, confirm applied stop protection and zero, perform only authorized "
                "cleanup/rollback, and retain exact settlement and accepted-source evidence. "
                "Do not start a new experiment or repeat an uncertain operation."
            )
        elif scope == "correction":
            instructions = (
                "Correct the previous output using the feedback and original native records. "
                "This is evidence-reading/reporting scope only; do not modify product source, "
                "deploy, allocate exposure or repeat an uncertain action."
            )
            context["previous_output"] = data.get("task", {}).get("result", {}).get("output", {})
        task = AgentTask(
            id=str(uuid4()),
            run_id=record.id,
            cycle=data["cycle"],
            step=data["step"],
            attempt=data.get("attempt", 0) + 1,
            runner=setting.agent or config.default_agent,
            instructions=instructions
            + "\n"
            + setting.instructions
            + "\nReturn the supplied result envelope. End this invocation when yielding. "
            "The actual host tool scope is authoritative.",
            context=context,
            output_schema=_OUTPUT_SCHEMA,
            workspace=config.workspace,
            deadline=self.clock.now() + timedelta(seconds=setting.timeout_seconds),
            max_cost=setting.max_cost,
            tool_profile=setting.tool_profile,
            purpose=purpose,
            scope=scope,
            predecessor=data.get("task", {}).get("task", {}).get("id"),
        )
        data["task"] = {
            "task": json_value(task.payload()),
            "status": "prepared",
            "result": None,
            "reservation_held": not reconcile,
        }
        data["current"] = task.id
        data["attempt"] = task.attempt
        if not reconcile:
            data["reserved_tasks"] += 1
        data["blocker"] = None
        record = await self._save(record, data, "task_prepared", lease)
        await self._process(record, data, lease)

    def _expected(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {
            name: data[name]
            for name in (
                "source_baseline",
                "candidate",
                "artifact",
                "deployment_id",
                "canary_id",
                "experiment_id",
                "experiment_started_at",
                "experiment_deadline",
                "unresolved_tasks",
                "stop_request_id",
                "cycle",
            )
            if name in data
        } | {"plan_fingerprint": canonical_hash(data.get("cycle_plan", data["config"]["plan"]))}

    async def _read(
        self,
        record: Record,
        data: dict[str, Any],
        task: AgentTask,
        result: AgentResult | None,
        *,
        purpose: str = "handoff",
    ) -> Verification:
        principal = await self._principal(
            "run:advance", record.project_id, set(data["read_claims"])
        )
        request = EvidenceRequest(
            task=task,
            result=result,
            expected=self._expected(data),
            purpose=purpose,
            boundary=data["scope"],
        )
        return await self._call(self.infrastructure.read_evidence(request, principal))

    def _valid(self, task: AgentTask, verification: Verification) -> bool:
        now = self.clock.now()
        return (
            verification.task_fingerprint == task.fingerprint
            and verification.observed_at <= now < verification.valid_until
            and bool(verification.evidence)
        )

    @staticmethod
    def _claims(data: dict[str, Any], verification: Verification) -> None:
        data["read_claims"] = sorted(
            set(data["read_claims"])
            | {claim for evidence in verification.evidence for claim in evidence.read_claims}
        )

    async def _process(self, record: Record, data: dict[str, Any], lease: Lease) -> None:
        entry = data["task"]
        task = _task(entry["task"])
        if task.purpose == "reconcile" and entry["status"] == "prepared":
            # Native-only closure remains available without any model registration,
            # remaining invocation capacity, or ordinary approval.
            if await self._verify(record, data, lease, task, None, purpose="settlement"):
                return
        runner = self.runners.get(task.runner)
        if runner is None:
            await self._wait(record, data, "original agent is not registered", lease)
            return
        if entry.get("result") is not None:
            result = _result(entry["result"])
            await self._verify(record, data, lease, task, result)
            return
        if entry["status"] == "prepared":
            if task.purpose == "reconcile":
                if not entry.get("reservation_held"):
                    if data["cleanup_reserved"] >= self._frozen_config(record).cleanup_tasks:
                        await self._wait(
                            record,
                            data,
                            "cleanup allowance exhausted; independent stopping continues",
                            lease,
                        )
                        return
                    data["cleanup_reserved"] += 1
                    entry["reservation_held"] = True
                    record = await self._save(record, data, "task_reserved", lease)
            principal = await self._principal(
                "run:advance", record.project_id, set(data["read_claims"])
            )
            try:
                approval = await self._call(self.infrastructure.authorize(task, principal))
            except Exception as error:
                await self._wait(
                    record, data, f"authorization unavailable: {type(error).__name__}", lease
                )
                return
            entry["authorization"] = json_value(approval)
            if not _authorized(approval, task, self.clock.now()):
                await self._wait(
                    record,
                    data,
                    f"authorization {approval.status.value}: "
                    f"{approval.reason or approval.reference}",
                    lease,
                )
                return
            if task.purpose != "reconcile" and (
                data.get("hold_requested") or data["status"] == "held"
            ):
                await self._wait(record, data, "scheduling held", lease)
                return
            if self.clock.now() >= task.deadline:
                await self._wait(
                    record,
                    data,
                    "approved proposal expired before launch; new proposal required",
                    lease,
                )
                return
            if task.scope in {"preparation_canary", "main_exposure", "disposition"}:
                try:
                    safety = await self._safety(record)
                except Exception:
                    safety = None
                if safety is None or not self._fresh_safe(safety):
                    await self._wait(
                        record, data, "fresh protection and readiness required before launch", lease
                    )
                    return
            entry["status"] = "launching"
            data["cleanup_count" if task.purpose == "reconcile" else "task_count"] += 1
            record = await self._save(record, data, "task_dispatch_intent", lease)
            # Fence/revision and authenticated authority are checked again at
            # the last boundary before dispatch, outside the SQLite transaction.
            await self._principal("run:advance", record.project_id, set(data["read_claims"]))
            record = await self._save(record, data, "dispatch_authorized", lease)
            if self.clock.now() >= min(approval.valid_until, task.deadline):
                entry["status"] = "prepared"
                data["cleanup_count" if task.purpose == "reconcile" else "task_count"] -= 1
                await self._wait(
                    record, data, "authorization or proposal expired before dispatch", lease
                )
                return
            try:
                ref = await self._call(runner.start(task))
                if ref != ExecutionRef(task.id, task.id):
                    raise ValueError("runner changed stable execution identity")
            except Exception as error:
                await self._wait(
                    record,
                    data,
                    f"launch outcome unknown ({type(error).__name__}); observe original task",
                    lease,
                )
                return
            entry["status"] = "running"
            data["wake_at"] = utc_text(self.clock.now())
            data["blocker"] = None
            await self._save(record, data, "task_started", lease)
            return
        ref = ExecutionRef(task.id, task.id)
        try:
            if self.clock.now() >= task.deadline and not entry.get("cancel_requested"):
                entry["cancel_requested"] = True
                record = await self._save(record, data, "cancel_intent", lease)
                result = await self._call(runner.cancel(ref))
            else:
                result = await self._call(runner.observe(ref))
        except Exception as error:
            await self._wait(
                record, data, f"original execution unknown: {type(error).__name__}", lease
            )
            return
        if result.execution != ref:
            await self._wait(record, data, "agent execution identity mismatch", lease)
            return
        if result.status is AgentStatus.PENDING:
            await self._wait(record, data, "original execution pending", lease)
            return
        if result.status in _ENDED:
            entry["result"] = json_value(result)
            entry["status"] = "result"
            record = await self._save(record, data, "task_output_saved", lease)
        await self._verify(record, data, lease, task, result)

    async def _verify(
        self,
        record: Record,
        data: dict[str, Any],
        lease: Lease,
        task: AgentTask,
        result: AgentResult | None,
        *,
        purpose: str = "handoff",
    ) -> bool:
        try:
            verification = await self._read(record, data, task, result, purpose=purpose)
        except Exception as error:
            if purpose == "settlement" and result is None:
                return False
            await self._wait(
                record,
                data,
                f"evidence unavailable: {type(error).__name__}; inspect protected host diagnostics",
                lease,
            )
            return True
        if not self._valid(task, verification):
            await self._wait(record, data, "stale or mismatched evidence", lease)
            return True
        self._claims(data, verification)
        facts = json_value(verification.facts)
        terminal = (
            result is None or result.status in _ENDED or facts.get("execution_fenced") is True
        )
        if not terminal:
            await self._wait(record, data, "original execution remains capable of effects", lease)
            return True
        if result is not None and data["task"].get("result") is None:
            data["task"]["result"] = json_value(result)
            data["task"]["status"] = "result"
            record = await self._save(record, data, "task_output_saved", lease)
        if (
            purpose == "settlement"
            and result is None
            and verification.status is not VerificationStatus.VERIFIED
        ):
            return False
        if verification.status in {VerificationStatus.WAITING, VerificationStatus.UNKNOWN}:
            await self._wait(
                record,
                data,
                verification.reason or "named native evidence pending",
                lease,
                wake_at=facts.get("wake_at"),
            )
            return True
        if purpose != "settlement":
            principal = await self._principal(
                "run:advance", record.project_id, set(data["read_claims"])
            )
            try:
                approval = await self._call(
                    self.infrastructure.authorize(task, principal, purpose="handoff")
                )
            except Exception as error:
                await self._wait(
                    record, data, f"handoff authority unavailable: {type(error).__name__}", lease
                )
                return True
            if not _authorized(approval, task, self.clock.now()):
                await self._wait(record, data, "current handoff authority pending or denied", lease)
                return True
        if (
            result is not None
            and result.output.get("outcome") == "blocked"
            and facts.get("blocker_resolved") is not True
        ):
            blocker = result.output.get("blocker")
            reason = (
                f"{blocker.get('reason', 'missing information')} "
                f"(owner: {blocker.get('owner', 'host')})"
                if isinstance(blocker, Mapping)
                else "blocked output requires a named dependency"
            )
            await self._wait(record, data, reason, lease)
            return True
        envelope_error = (
            _envelope(result)
            if result is not None and result.status is AgentStatus.COMPLETED
            else None
        )
        if (
            verification.status in {VerificationStatus.REJECTED, VerificationStatus.RETRY_SAFE}
            or envelope_error
        ):
            await self._correct(
                record,
                data,
                lease,
                task,
                verification,
                envelope_error or verification.reason or "handoff evidence rejected",
            )
            return True
        try:
            updated, event = complete(data, facts, self._frozen_config(record), self.clock.now())
        except InvalidEvidence as error:
            if purpose == "settlement" and result is None:
                return False
            await self._correct(record, data, lease, task, verification, str(error))
            return True
        entry = updated["task"]
        if result is None and task.purpose == "reconcile" and entry.get("reservation_held"):
            updated["cleanup_reserved"] -= 1
            entry["reservation_held"] = False
        entry["verification"] = json_value(verification)
        if result is not None:
            updated["checkpoint"] = json_value(result.output.get("checkpoint", {}))
        updated["last_evidence"] = json_value(verification.evidence)
        updated["retry_feedback"] = None
        updated["corrections"] = 0
        if event != "blocked":
            updated["blocker"] = None
        if event in {"waiting", "blocked"} and not facts.get("resume_required"):
            entry["status"] = "waiting"
            # Observation time/validity refresh alone is not a history change.
            old = record.data.get("task", {}).get("verification")
            if (
                old
                and {
                    **entry["verification"],
                    "observed_at": old["observed_at"],
                    "valid_until": old["valid_until"],
                }
                == old
            ):
                entry["verification"] = old
            comparison = {**updated, "wake_at": record.data.get("wake_at")}
            if comparison == record.data:
                return True
        else:
            entry["status"] = "accepted"
            updated["current"] = None
            if updated["status"] not in _TERMINAL and not updated.get("wake_at"):
                updated["wake_at"] = utc_text(self.clock.now())
        if updated["cycle"] != data["cycle"]:
            updated["canary_id"] = f"{record.id}:{updated['cycle']}:canary"
            updated["experiment_id"] = f"{record.id}:{updated['cycle']}:experiment"
            updated["cycle_started_at"] = utc_text(self.clock.now())
            updated["attempt"] = 0
        if data.get("hold_requested") and updated["status"] == "active":
            updated["status"] = "held"
        await self._save(record, updated, f"{task.step}:{event}", lease)
        return True

    async def _correct(
        self,
        record: Record,
        data: dict[str, Any],
        lease: Lease,
        task: AgentTask,
        verification: Verification,
        reason: str,
    ) -> None:
        facts = verification.facts
        # Reporting-only correction still needs settled original effects. A
        # rejected statement never creates retry permission by itself.
        if facts.get("effects_settled") is not True or facts.get("correction_safe") is not True:
            await self._wait(
                record,
                data,
                f"handoff blocked: {reason}; effects/correction authority unresolved",
                lease,
            )
            return
        data["task"]["verification"] = json_value(verification)
        data["task"]["status"] = "rejected"
        data["corrections"] += 1
        data["current"] = None
        data["retry_feedback"] = {
            "task_id": task.id,
            "result_reference": f"cddai:task:{task.id}:result",
            "reason": reason[:500],
            "original_scope": data["scope"],
        }
        data["wake_at"] = utc_text(self.clock.now())
        data["blocker"] = reason[:500]
        await self._save(record, data, "correction_required", lease)

    def _stop_request(self, record: Record, data: dict[str, Any]) -> StopRequest:
        if data.get("stop_request"):
            return StopRequest(**data["stop_request"])
        task = _task(data["task"]["task"]) if data.get("current") else None
        request = StopRequest(
            request_id=data["stop_request_id"],
            project_id=record.project_id,
            run_id=record.id,
            resource_id=data["config"]["resource_id"],
            reason=data["stop_reason"],
            task_ids=(task.id,) if task else (),
            task_fingerprints=(task.fingerprint,) if task else (),
            expected=self._expected(data),
        )
        data["stop_request"] = json_value(request)
        return request

    async def _deliver_stop(
        self, record: Record, data: dict[str, Any], principal: Principal
    ) -> None:
        request = self._stop_request(record, data)
        if data.get("stop_delivery", {}).get("accepted"):
            return
        try:
            delivery = await self._call(self.infrastructure.request_stop(request, principal))
            if delivery.request_id != request.request_id:
                raise ValueError("stop request identity mismatch")
        except Exception as error:
            data["stop_delivery_error"] = type(error).__name__
        else:
            data["stop_delivery"] = json_value(delivery)
            data.pop("stop_delivery_error", None)

    async def _stopping(self, record: Record, data: dict[str, Any], lease: Lease) -> None:
        task = _task(data["task"]["task"]) if data.get("current") else None
        if not data.get("stop_delivery", {}).get("accepted"):
            if not data.get("stop_request"):
                self._stop_request(record, data)
                record = await self._save(record, data, "stop_delivery", lease)
            principal = await self._principal(
                "run:advance", record.project_id, set(data["read_claims"])
            )
            await self._deliver_stop(record, data, principal)
            if data != record.data:
                record = await self._save(record, data, "stop_delivery", lease)
        if task is None:
            await self._prepare(record, data, lease, reconcile=True)
            return
        if task.purpose == "reconcile":
            await self._process(record, data, lease)
            return
        entry = data["task"]
        if entry["status"] == "prepared":
            entry["status"] = "cancelled"
            data["reserved_tasks"] -= 1
            data["current"] = None
            await self._save(record, data, "unlaunched_task_cancelled", lease)
            return
        result = _result(entry["result"]) if entry.get("result") is not None else None
        if result is None:
            runner = self.runners.get(task.runner)
            if runner is None:
                await self._wait(
                    record,
                    data,
                    "original agent is not registered; independent stop requested",
                    lease,
                )
                return
            ref = ExecutionRef(task.id, task.id)
            try:
                if not entry.get("cancel_requested"):
                    entry["cancel_requested"] = True
                    record = await self._save(record, data, "cancel_intent", lease)
                    result = await self._call(runner.cancel(ref))
                else:
                    result = await self._call(runner.observe(ref))
            except Exception as error:
                await self._wait(
                    record, data, f"stopping execution unknown: {type(error).__name__}", lease
                )
                return
            if result.execution != ref:
                await self._wait(record, data, "stopping execution identity mismatch", lease)
                return
            if result.status in _ENDED:
                entry["result"] = json_value(result)
                record = await self._save(record, data, "task_output_saved", lease)
        try:
            verification = await self._read(record, data, task, result, purpose="settlement")
        except Exception:
            verification = None
        valid = verification is not None and self._valid(task, verification)
        if result.status not in _ENDED and not (
            valid
            and verification is not None
            and verification.facts.get("execution_fenced") is True
        ):
            await self._wait(
                record, data, "original execution not terminal or fenced; stopping continues", lease
            )
            return
        if valid and verification is not None:
            self._claims(data, verification)
            entry["verification"] = json_value(verification)
        entry["status"] = "interrupted"
        data["unresolved_tasks"] = [
            *data.get("unresolved_tasks", []),
            {
                "task_id": task.id,
                "task_fingerprint": task.fingerprint,
                "execution": json_value(ExecutionRef(task.id, task.id)),
                "operations": json_value(result.output.get("operations", [])),
            },
        ]
        data["current"] = None
        await self._save(record, data, "reconciliation_required", lease)

    async def run_worker(self, stop_event: asyncio.Event, *, interval: float = 1.0) -> None:
        if interval <= 0:
            raise ValueError("worker interval must be positive")
        next_checks: dict[str, tuple[int, float]] = {}
        loop = asyncio.get_running_loop()
        while not stop_event.is_set():
            # A native evidence deadline is not a safety-check deadline. Inspect
            # current nonterminal runs cheaply even while their agent is yielded.
            for record in await self.store.list_due(self.clock.now(), include_waiting=True):
                if stop_event.is_set():
                    return
                previous = next_checks.get(record.id)
                if previous and previous[0] == record.revision and loop.time() < previous[1]:
                    continue
                view = await self.advance(record.id)
                if (
                    view.blocker
                    or view.data.get("task", {}).get("status") == "waiting"
                    or (view.wake_at and timestamp(view.wake_at) > self.clock.now())
                ):
                    next_checks[record.id] = (
                        view.revision,
                        loop.time() + record.data["config"]["poll_seconds"],
                    )
                else:
                    next_checks.pop(record.id, None)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                pass
