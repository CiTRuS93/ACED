"""Agent-neutral task execution; runners never decide lifecycle transitions."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from aced._json import canonical_hash, canonical_text, freeze, utc_text


@dataclass(frozen=True)
class AgentTask:
    """Immutable assignment prepared by the coordinator for one agent attempt.

    ``max_cost`` is an envelope for host-enforced spending, not an assurance that
    every runner can measure or enforce monetary cost. Zero uses host-default
    limits. The workspace and tool
    profile must be prepared and isolated by the host.
    """

    id: str
    run_id: str
    cycle: int
    step: str
    attempt: int
    runner: str
    instructions: str
    context: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    workspace: Path
    deadline: datetime
    max_cost: float
    tool_profile: str
    purpose: str = "work"
    scope: str = "research"
    predecessor: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "run_id", "step", "runner", "instructions", "tool_profile"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be nonempty")
        if self.cycle < 1 or self.attempt < 1:
            raise ValueError("cycle and attempt must be positive")
        if self.purpose not in {"work", "reconcile"} or not self.scope.strip():
            raise ValueError("invalid task purpose or scope")
        if not math.isfinite(self.max_cost) or self.max_cost < 0:
            raise ValueError("max_cost must be nonnegative and finite")
        utc_text(self.deadline)
        object.__setattr__(self, "context", freeze(self.context))
        object.__setattr__(self, "output_schema", freeze(self.output_schema))
        # Validate canonical serializability at the boundary, including finite numbers.
        canonical_text(self.payload())

    def payload(self) -> dict[str, Any]:
        """Canonical task representation; Path is deliberately converted here."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "cycle": self.cycle,
            "step": self.step,
            "attempt": self.attempt,
            "runner": self.runner,
            "instructions": self.instructions,
            "context": self.context,
            "output_schema": self.output_schema,
            "workspace": str(self.workspace),
            "deadline": utc_text(self.deadline),
            "max_cost": self.max_cost,
            "tool_profile": self.tool_profile,
            "purpose": self.purpose,
            "scope": self.scope,
            "predecessor": self.predecessor,
        }

    @property
    def instruction_digest(self) -> str:
        return canonical_hash(self.instructions)

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.payload())


@dataclass(frozen=True)
class ExecutionRef:
    task_id: str
    job_id: str


class AgentStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    ABSENT = "absent"


@dataclass(frozen=True)
class AgentResult:
    status: AgentStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    execution: ExecutionRef | None = None
    reason: str = ""
    usage: float | None = None

    def __post_init__(self) -> None:
        if self.usage is not None and (not math.isfinite(self.usage) or self.usage < 0):
            raise ValueError("usage must be nonnegative and finite, or unknown")
        object.__setattr__(self, "output", freeze(self.output))
        canonical_text(self.output)


class AgentRunner(Protocol):
    """A host-trusted runner; cancellation says nothing about external effects."""

    async def start(self, task: AgentTask) -> ExecutionRef: ...

    async def observe(self, reference: ExecutionRef) -> AgentResult: ...

    async def cancel(self, reference: ExecutionRef) -> AgentResult: ...
