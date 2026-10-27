"""Optional manager host interfaces. These display host facts, never authorize effects."""

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from aced.models import Inspection, Principal


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ApprovalRequest(Model):
    id: str
    run_id: str
    task_id: str
    task_fingerprint: str
    boundary: str
    summary: str
    inputs: dict[str, Any]
    expires_at: AwareDatetime
    status: Literal["pending", "approved", "denied", "expired"] = "pending"


class ApprovalDecision(Model):
    task_fingerprint: str = Field(min_length=1, max_length=256)
    decision: Literal["approve", "deny"]
    key: str = Field(min_length=1, max_length=128)


class ApprovalAdapter(Protocol):
    async def list_requests(
        self, run: Inspection, principal: Principal
    ) -> tuple[ApprovalRequest, ...]: ...

    async def decide(
        self, run: Inspection, request_id: str, decision: ApprovalDecision, principal: Principal
    ) -> ApprovalRequest:
        """Reauthorize approver, exact fingerprint and expiry; deduplicate key at the host."""
        ...


class MetricPoint(Model):
    at: AwareDatetime
    value: float | None


class MetricSeries(Model):
    name: str
    unit: str
    points: list[MetricPoint] = Field(max_length=1000)
    guardrail: float | None = None
    interpretation: str = ""


class ExperimentSnapshot(Model):
    run_id: str
    cycle: int = Field(ge=1)
    phase: Literal["canary", "main"]
    experiment_id: str
    observed_at: AwareDatetime
    fresh_until: AwareDatetime
    exposure: Literal["active", "zero", "unknown"]
    safety: str
    allocation_percent: float | None = Field(default=None, ge=0, le=100)
    deadline: AwareDatetime | None = None
    readout: str = "Unavailable"
    provenance: list[str] = Field(max_length=32)
    series: list[MetricSeries] = Field(default_factory=list, max_length=16)


class MetricsAdapter(Protocol):
    async def read(
        self,
        run: Inspection,
        principal: Principal,
        *,
        cycle: int,
        phase: Literal["canary", "main"],
        experiment_id: str,
        start: datetime,
        end: datetime,
        max_points: int,
    ) -> ExperimentSnapshot:
        """Return authoritative, scoped host facts; enforce evidence access and bounded queries."""
        ...
