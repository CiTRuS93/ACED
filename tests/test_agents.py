"""Boundary tests for immutable agent-neutral task records."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aced.agents import AgentResult, AgentStatus, AgentTask, ExecutionRef


def task(tmp_path: Path) -> AgentTask:
    return AgentTask(
        "task-1",
        "run-1",
        1,
        "implement",
        1,
        "codex",
        "Implement the proposal",
        {"source": "abc", "learning": ["a"]},
        {"type": "object"},
        tmp_path,
        datetime(2030, 1, 1, tzinfo=UTC),
        1.0,
        "default",
    )


def test_task_copies_context_and_hashes_all_identity(tmp_path):
    assignment = task(tmp_path)
    assert assignment.payload()["workspace"] == str(tmp_path)
    assert assignment.fingerprint == replace(assignment).fingerprint
    assert assignment.fingerprint != replace(assignment, runner="claude").fingerprint
    assert assignment.fingerprint != replace(assignment, id="task-2").fingerprint
    with pytest.raises(TypeError):
        assignment.context["source"] = "replacement"
    original = {"nested": ["a"]}
    copied = replace(assignment, context=original)
    original["nested"].append("b")
    assert copied.context["nested"] == ("a",)


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"instructions": " "},
        {"cycle": 0},
        {"attempt": 0},
        {"max_cost": -1},
        {"max_cost": float("inf")},
        {"deadline": datetime(2030, 1, 1)},
        {"context": {"bad": float("nan")}},
    ],
)
def test_invalid_task_boundaries(tmp_path, change):
    with pytest.raises(ValueError):
        replace(task(tmp_path), **change)


def test_zero_cost_means_host_limit_and_unknown_usage_is_not_zero(tmp_path):
    assert replace(task(tmp_path), max_cost=0).max_cost == 0
    result = AgentResult(AgentStatus.PENDING, execution=ExecutionRef("a", "a"))
    assert result.usage is None
    assert result.execution.task_id == "a"
    with pytest.raises(TypeError):
        result.output["changed"] = True
    for invalid in [-1, float("inf"), float("nan")]:
        with pytest.raises(ValueError):
            AgentResult(AgentStatus.COMPLETED, usage=invalid)
    assert AgentResult(AgentStatus.COMPLETED, usage=0).usage == 0
