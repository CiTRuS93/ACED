"""Deterministic, isolated reference composition. No model or product is contacted."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ._json import canonical_hash, json_value, utc_text
from .agents import AgentResult, AgentStatus, AgentTask, ExecutionRef
from .models import (
    ApprovalStatus,
    Authorization,
    Evidence,
    EvidenceRequest,
    ExperimentPlan,
    Goal,
    Principal,
    ProjectConfig,
    SafetyStatus,
    StopDelivery,
    StopRequest,
    Verification,
    VerificationStatus,
)
from .runtime import Runtime


@dataclass
class DemoClock:
    value: datetime = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def tick(self, seconds: int = 1) -> None:
        self.value += timedelta(seconds=seconds)


class DemoIdentity:
    def __init__(self) -> None:
        self.principal = Principal("fixture-service", frozenset({"run:*", "project:*"}))

    async def authenticate(self, context: object) -> Principal:
        return self.principal


def envelope(outcome: str = "completed", **values: Any) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "summary": "fixture result",
        "deliverable": {},
        "evidence": ["fixture:receipt"],
        "operations": [],
        "checkpoint": {},
        "wait": None,
        "blocker": None,
        **values,
    }


class DemoRunner:
    def __init__(self, infrastructure: DemoInfrastructure | None = None) -> None:
        self.infrastructure = infrastructure
        self.tasks: dict[str, AgentTask] = {}
        self.starts: list[str] = []
        self.cancelled: set[str] = set()
        self.pending = False
        self.lose_start_response = False
        self.output: dict[str, Any] | None = None
        self.observations = 0

    async def start(self, task: AgentTask) -> ExecutionRef:
        if task.id not in self.tasks:
            self.tasks[task.id] = task
            self.starts.append(task.id)
            if self.infrastructure is not None:
                self.infrastructure.execute(task)
        if self.lose_start_response:
            raise OSError("fixture lost response")
        return ExecutionRef(task.id, task.id)

    async def observe(self, reference: ExecutionRef) -> AgentResult:
        self.observations += 1
        if reference.task_id not in self.tasks:
            return AgentResult(AgentStatus.ABSENT, execution=reference)
        if reference.task_id in self.cancelled:
            return AgentResult(AgentStatus.CANCELLED, execution=reference)
        if self.pending:
            return AgentResult(AgentStatus.PENDING, execution=reference)
        return AgentResult(
            AgentStatus.COMPLETED, self.output if self.output is not None else envelope(), reference
        )

    async def cancel(self, reference: ExecutionRef) -> AgentResult:
        self.cancelled.add(reference.task_id)
        return AgentResult(AgentStatus.CANCELLED, execution=reference)


def demo_project(workspace: Path) -> ProjectConfig:
    return ProjectConfig(
        "demo",
        workspace,
        "source-0",
        ExperimentPlan(
            metric="activation",
            decision_rule="fixture-native-rule",
            canary_cohort="canary",
            experiment_cohort="experiment",
            canary_percent=1,
            experiment_percent=10,
            canary_min_samples=10,
            canary_min_seconds=2,
            canary_max_seconds=40,
            experiment_seconds=10,
            monitor_grace_seconds=5,
            guardrails=("errors",),
            readout_delay_seconds=2,
            observation_seconds=2,
        ),
        default_agent="demo",
        max_cycles=2,
        required_checks=("tests", "instrumentation"),
    )


class DemoInfrastructure:
    """An independent fixture ledger; fake agent effects occur in execute, not reads."""

    def __init__(self, clock: DemoClock) -> None:
        self.clock = clock
        self.approval = ApprovalStatus.ALLOWED
        self.healthy = True
        self.independent_stop_ready = True
        self.verification = VerificationStatus.VERIFIED
        self.overrides: dict[str, Any] = {}
        self.claims: frozenset[str] = frozenset()
        self.ledger: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, AgentTask] = {}
        self.proposals: dict[str, AgentTask] = {}
        self.native_plan = demo_project(Path.cwd()).plan
        self.stop_receipts: dict[str, dict[str, Any]] = {}
        self.exposures: dict[str, dict[str, Any]] = {}
        self.stop_requests: list[str] = []
        self.stop_latched = False
        self.stopped_exposure_ids: set[str] = set()
        self.lose_stop_response = False
        self.monitor_first = True
        self.outcome = "promote"
        self.valid_result = True
        self.continue_cycles = 2
        self.repair = False
        self.unsuccessful = False
        self.retained_source = "source-0"

    async def authorize(
        self, task: AgentTask, principal: Principal, *, purpose: str = "dispatch"
    ) -> Authorization:
        if purpose not in {"dispatch", "handoff"}:
            raise ValueError("unknown authorization purpose")
        previous = self.proposals.setdefault(task.id, task)
        if previous.fingerprint != task.fingerprint:
            raise ValueError("fixture task proposal identity changed")
        return Authorization(
            self.approval,
            task.fingerprint,
            "fixture:authorization",
            self.clock.now() + timedelta(hours=1),
        )

    def monitor(self) -> None:
        now = self.clock.now()
        for item in self.exposures.values():
            end = item["review_end"] if item["kind"] == "canary" else item["end"]
            if not item["zero"] and (now >= end or self.stop_latched):
                item["zero"] = True
                item["ended"] = min(now, end)

    async def safety(self, project_id: str, run_id: str, principal: Principal) -> SafetyStatus:
        if self.monitor_first:
            self.monitor()
        active = next(
            (
                item
                for item in reversed(list(self.exposures.values()))
                if item["run_id"] == run_id and not item["zero"]
            ),
            None,
        )
        now = self.clock.now()
        validity = now + timedelta(seconds=30)
        observed = now
        if active and now >= active["end"]:
            # Precisely model the old monitor-before/coordinator-before race.
            observed = active["end"] - timedelta(seconds=1)
            validity = active["end"]
        return SafetyStatus(
            self.healthy,
            self.independent_stop_ready,
            observed,
            validity,
            "fixture:health",
            zero_confirmed=active is None,
            exposure_active=active is not None,
            exposure_end=active["end"] if active else None,
            stop_required=not self.healthy,
            protection_applied=self.stop_latched,
            experiment_id=active["id"] if active else None,
            candidate=active["candidate"] if active else None,
            plan_fingerprint=active["plan_fingerprint"] if active else None,
        )

    async def request_stop(self, request: StopRequest, principal: Principal) -> StopDelivery:
        self.stop_requests.append(request.request_id)
        self.stop_latched = True
        self.stopped_exposure_ids.update(
            target
            for name in ("canary_id", "experiment_id")
            if isinstance(target := request.expected.get(name), str)
        )
        self.stopped_exposure_ids.update(
            key for key, item in self.exposures.items() if item["run_id"] == request.run_id
        )
        self.monitor()
        receipt = self.stop_receipts.get(request.request_id)
        if receipt is not None:
            if receipt["run_id"] != request.run_id or receipt["resource_id"] != request.resource_id:
                raise ValueError("fixture stop identity belongs to another resource")
        else:
            # The receipt observes the native fixture ledger once. A later read
            # cannot turn caller expectations into source/task settlement facts.
            native = [
                task
                for task in self.tasks.values()
                if task.run_id == request.run_id and task.purpose != "reconcile"
            ]
            last = self.ledger[native[-1].id] if native else {}
            identities: dict[str, Any] = {
                name: last[name]
                for name in (
                    "source_baseline",
                    "candidate",
                    "artifact",
                    "deployment_id",
                    "canary_id",
                    "experiment_id",
                    "plan_fingerprint",
                )
                if name in last
            }
            if not native:
                identities.update(
                    source_baseline=self.retained_source,
                    plan_fingerprint=self.native_plan.fingerprint,
                )
                # Before any execution, these are verified absence lookups, not
                # fabricated deployment or experiment receipts. Preserve their
                # exact requested targets in the stop receipt for later reads.
                for name in ("canary_id", "experiment_id"):
                    target = request.expected.get(name)
                    if isinstance(target, str) and target not in self.exposures:
                        identities[name] = target
            self.stop_receipts[request.request_id] = {
                "run_id": request.run_id,
                "resource_id": request.resource_id,
                "identities": identities,
                "absent_exposure": not native,
            }
        if self.lose_stop_response:
            raise OSError("fixture lost stop response")
        return StopDelivery(request.request_id, True, "fixture:stop")

    def execute(self, task: AgentTask) -> None:
        """Fake agent/tool effects under a frozen task; repeats never allocate again."""
        if task.id in self.ledger:
            return
        self.tasks[task.id] = task
        ctx, now = task.context, self.clock.now()
        plan = ctx["plan"]
        scope = ctx.get("original_scope", task.scope) if task.scope == "correction" else task.scope
        facts: dict[str, Any] = {
            "execution_settled": True,
            "effects_settled": True,
            "correction_safe": True,
            "plan_fingerprint": canonical_hash(plan),
            "source_baseline": ctx["source_baseline"],
            "candidate": ctx.get("candidate", f"source-{task.cycle}"),
            "artifact": ctx.get("artifact", f"artifact-{task.cycle}"),
            "deployment_id": ctx.get("deployment_id", f"deployment-{task.cycle}"),
            "canary_id": ctx["canary_id"],
            "experiment_id": ctx["experiment_id"],
        }
        if scope == "research":
            selected = "candidate-a" if task.cycle == 1 else "candidate-b"
            facts.update(
                hypothesis="A smaller first action improves activation",
                plan=plan,
                plan_authorized=True,
                plan_authorization_reference=f"fixture:plan-approval:{task.id}",
                plan_authorization_fingerprint=canonical_hash(plan),
                selected_candidate_id=selected,
                research_reference=f"fixture:research:{task.cycle}",
                candidates=[
                    {
                        "id": identifier,
                        "claim": "Reduce activation friction",
                        "evidence": ["fixture:baseline"],
                        "assumptions": ["Traffic represents eligible users"],
                        "expected_learning": "Whether reduced friction improves activation",
                        "effort": "small",
                        "risk": "reversible",
                        "dependencies": [] if identifier == "candidate-a" else ["candidate-a"],
                        "rationale": "Highest learning per effort given accepted source",
                        "status": "selected" if identifier == selected else "deferred",
                    }
                    for identifier in ("candidate-a", "candidate-b")
                ],
                initiative={
                    "id": "initiative-1",
                    "phase_id": str(task.cycle),
                    "dependencies": [] if task.cycle == 1 else ["1"],
                    "continuation_criteria": "Re-evaluate phase after earlier learning",
                },
            )
        elif scope == "implementation":
            facts.update(
                checks=dict.fromkeys(ctx["required_checks"], True),
                observability={
                    "reference": "fixture:instrumentation",
                    "queries": ["fixture:errors-by-candidate"],
                    "monitoring_instructions": "Inspect traffic and errors by candidate",
                    "missing_data_policy": "Missing traffic or telemetry is unknown health",
                    "normal_verified": True,
                    "failure_verified": True,
                    "guardrails": plan["guardrails"],
                },
            )
        elif scope in {"preparation_canary", "main_exposure"}:
            canary = scope == "preparation_canary"
            key = ctx["canary_id" if canary else "experiment_id"]
            if key in self.stopped_exposure_ids:
                raise PermissionError("fixture stop receipt prevents late re-exposure")
            if self.stop_latched:
                # A completed, explicitly authorized repair has new identities.
                if not ctx.get("repair_context"):
                    raise PermissionError("fixture stop latch prevents re-exposure")
                self.stop_latched = False
            seconds = plan["canary_max_seconds" if canary else "experiment_seconds"]
            self.exposures.setdefault(
                key,
                {
                    "id": key,
                    "run_id": task.run_id,
                    "candidate": facts["candidate"],
                    "plan_fingerprint": facts["plan_fingerprint"],
                    "start": now,
                    "end": now + timedelta(seconds=seconds),
                    "review_end": now + timedelta(seconds=plan["canary_min_seconds"]),
                    "kind": "canary" if canary else "main",
                    "zero": False,
                },
            )
            facts.update(
                cohort=plan["canary_cohort" if canary else "experiment_cohort"],
                allocation_percent=plan["canary_percent" if canary else "experiment_percent"],
                deadline_stop_armed=True,
                serving_candidate=facts["candidate"],
                ready_before_exposure=True,
                telemetry_verified=True,
                canary_excluded=True,
                healthy=True,
                checks_passed=True,
                samples=100,
                _exposure=key,
            )
        elif scope == "decision" and ctx.get("outcome") == "promote" and ctx.get("valid_result"):
            facts.update(
                proposed_disposition="promoted",
                proposal_reference=f"fixture:proposal:{task.id}",
                zero_confirmed=True,
                rollback_ready=True,
                independent_stop_ready=True,
            )
        elif scope in {"decision", "disposition"}:
            promote = scope == "disposition" and ctx.get("proposed_disposition") == "promoted"
            source = ctx["candidate"] if promote else ctx["source_baseline"]
            self.retained_source = source
            facts.update(
                disposition="promoted" if promote else "reverted",
                accepted_source=source,
                zero_confirmed=True,
                rollback_confirmed=True,
                promotion_confirmed=promote,
                rollback_ready=True,
                independent_stop_ready=True,
                promoted_at=utc_text(now),
                observation_complete=True,
                healthy=True,
                learning="Fixture learning with explicit uncertainty",
                learning_reference=f"fixture:learning:{task.cycle}",
                goal_assessment="attained" if promote else "undetermined",
                assessment_reason="Fixture evidence and remaining opportunities",
                next_action="repair"
                if self.repair and ctx.get("unsuccessful")
                else "next_hypothesis"
                if task.cycle < self.continue_cycles
                else "finish",
                repair_authorized=True,
            )
            if self.repair and ctx.get("unsuccessful"):
                self.unsuccessful = False
                self.repair = False
        self.ledger[task.id] = facts

    async def read_evidence(self, request: EvidenceRequest, principal: Principal) -> Verification:
        task = request.task
        status = self.verification
        if request.purpose == "settlement" or task.purpose == "reconcile":
            stop_id = task.context.get("stop_request_id")
            if stop_id is None:
                stop_id = next(
                    (
                        key
                        for key, receipt in reversed(self.stop_receipts.items())
                        if receipt["run_id"] == task.run_id
                    ),
                    None,
                )
            receipt = self.stop_receipts.get(stop_id) if isinstance(stop_id, str) else None
            registered = {**self.proposals, **self.tasks}
            native_tasks = [
                item
                for item in registered.values()
                if item.run_id == task.run_id and item.purpose != "reconcile"
            ]
            facts: dict[str, Any] = {
                **(json_value(receipt["identities"]) if receipt else {}),
                "execution_settled": True,
                "effects_settled": True,
                "zero_confirmed": all(item["zero"] for item in self.exposures.values()),
                "stop_request_id": stop_id,
                "stop_protection_applied": receipt is not None and self.stop_latched,
                "accepted_source": self.retained_source,
                "rollback_confirmed": True,
                "settled_tasks": [
                    {"task_id": item.id, "task_fingerprint": item.fingerprint}
                    for item in native_tasks
                ],
                "learning_unavailable": "No decision agent was requested after operator stop",
            }

        elif task.id not in self.ledger:
            return Verification(
                VerificationStatus.UNKNOWN,
                task.fingerprint,
                {},
                (Evidence("fixture:absent", "absent"),),
                self.clock.now(),
                self.clock.now() + timedelta(seconds=30),
                "original operation not established",
            )
        else:
            facts = json_value(self.ledger[task.id])
            key = facts.pop("_exposure", None)
            if key:
                item = self.exposures[key]
                canary = item["kind"] == "canary"
                facts.update(
                    started_at=utc_text(item["start"]),
                    deadline=utc_text(item["end"]),
                    zero_confirmed=item["zero"],
                )
                facts["canary_status" if canary else "experiment_status"] = (
                    ("passed" if canary else "closed")
                    if item["zero"]
                    else ("running" if canary else "active")
                )
                if item["zero"]:
                    facts["ended_at"] = utc_text(item["ended"])
                if not canary:
                    facts.update(
                        decision_rule=task.context["plan"]["decision_rule"],
                        valid=self.valid_result,
                        outcome=self.outcome,
                        readout_reference=f"fixture:readout:{key}",
                    )
                if self.unsuccessful and item["zero"]:
                    facts.update(
                        unsuccessful=True,
                        reason="fixture unsuccessful attempt",
                        main_started=not canary,
                    )
        facts.update(self.overrides)
        return Verification(
            status,
            task.fingerprint,
            facts,
            (Evidence("fixture:receipt", canonical_hash(facts), self.claims),),
            self.clock.now(),
            self.clock.now() + timedelta(seconds=30),
        )


async def conformance(database: str | Path = ":memory:") -> dict[str, Any]:
    clock = DemoClock()
    infra = DemoInfrastructure(clock)
    runner = DemoRunner(infra)
    config = demo_project(Path.cwd())
    async with Runtime(
        database,
        projects={"demo": config},
        runners={"demo": runner},
        infrastructure=infra,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        view = await runtime.start(Goal("demo", "Improve activation"), key="conformance")
        for _ in range(300):
            if view.status in {"completed", "stopped"}:
                break
            view = await runtime.advance(view.id)
            clock.tick()
        if view.status != "completed" or view.cycle != 2:
            raise RuntimeError(f"conformance failed at {view.step}: {view.blocker}")
        assert len(view.data["learning"]) == 2
        assert view.data["retained_source"] == "source-2"
        assert await runtime.store.verify_audit()
        return {
            "passed": True,
            "kind": "deterministic fixture",
            "cycles": view.cycle,
            "tasks": len(runner.starts),
            "audit_valid": True,
        }
