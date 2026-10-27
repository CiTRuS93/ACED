"""Durable agent-task handoffs, embedded in a host-owned operating envelope."""

from .agents import AgentResult, AgentRunner, AgentStatus, AgentTask, ExecutionRef
from .claude import ClaudeCliRunner
from .codex import CodexCliRunner
from .cursor import CursorCliRunner
from .models import (
    ApprovalMode,
    ApprovalPolicy,
    ApprovalStatus,
    Authorization,
    AuthorizationError,
    Evidence,
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
    StepConfig,
    StopDelivery,
    StopRequest,
    Verification,
    VerificationStatus,
)
from .opencode import OpenCodeCliRunner
from .runtime import Runtime
from .store import ConflictError, NotFoundError, SQLiteStore, StaleLeaseError, StoreError

__version__ = "0.1.0"
__all__ = [
    "AgentResult",
    "AgentRunner",
    "AgentStatus",
    "AgentTask",
    "ExecutionRef",
    "CodexCliRunner",
    "ClaudeCliRunner",
    "CursorCliRunner",
    "OpenCodeCliRunner",
    "ApprovalStatus",
    "ApprovalMode",
    "ApprovalPolicy",
    "Authorization",
    "AuthorizationError",
    "Evidence",
    "EvidenceRequest",
    "ExperimentPlan",
    "Goal",
    "IdentityProvider",
    "Infrastructure",
    "Inspection",
    "PlanBounds",
    "Principal",
    "ProjectConfig",
    "RunContinuation",
    "SafetyStatus",
    "Step",
    "StepConfig",
    "StopDelivery",
    "StopRequest",
    "Verification",
    "VerificationStatus",
    "Runtime",
    "ConflictError",
    "NotFoundError",
    "SQLiteStore",
    "StaleLeaseError",
    "StoreError",
]
