"""Local manager, installed with ``aced[manager]``; core imports remain dependency-free."""

from .app import create_manager_app
from .contracts import (
    ApprovalAdapter,
    ApprovalDecision,
    ApprovalRequest,
    ExperimentSnapshot,
    MetricPoint,
    MetricsAdapter,
    MetricSeries,
)

__all__ = [
    "create_manager_app",
    "ApprovalAdapter",
    "ApprovalDecision",
    "ApprovalRequest",
    "ExperimentSnapshot",
    "MetricPoint",
    "MetricSeries",
    "MetricsAdapter",
]
