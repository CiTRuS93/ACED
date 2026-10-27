"""Ephemeral offline console fixture; never loads product credentials or saved runs."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI

from aced._json import json_value
from aced.agents import AgentTask
from aced.models import ApprovalStatus, Authorization, Goal, Inspection, Principal, authorize
from aced.reference import DemoClock, DemoIdentity, DemoInfrastructure, DemoRunner, demo_project
from aced.runtime import Runtime
from aced.store import ConflictError

from .app import create_manager_app
from .contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ExperimentSnapshot,
    MetricPoint,
    MetricSeries,
)


class ConsoleFixture(DemoInfrastructure):
    def __init__(self, clock: DemoClock) -> None:
        super().__init__(clock)
        self.requests: dict[str, ApprovalRequest] = {}
        self.decisions: dict[str, tuple[str, ApprovalDecision]] = {}
        self.continue_cycles = 1
        self.outcome = "revert"  # Retain the configured source for continuation demonstrations.

    async def authorize(
        self, task: AgentTask, principal: Principal, *, purpose: str = "dispatch"
    ) -> Authorization:
        await super().authorize(task, principal, purpose=purpose)
        request = self.requests.setdefault(
            task.id,
            ApprovalRequest(
                id=task.id,
                run_id=task.run_id,
                task_id=task.id,
                task_fingerprint=task.fingerprint,
                boundary=task.scope,
                summary=f"Review {task.step} / {task.scope}",
                inputs=json_value(task.context),
                expires_at=self.clock.now() + timedelta(hours=1),
            ),
        )
        status = ApprovalStatus.WAITING
        if request.status == "approved" and request.expires_at > self.clock.now():
            status = ApprovalStatus.ALLOWED
        elif request.status == "denied":
            status = ApprovalStatus.DENIED
        return Authorization(
            status, task.fingerprint, f"fixture:approval:{task.id}", request.expires_at
        )

    async def list_requests(
        self, run: Inspection, principal: Principal
    ) -> tuple[ApprovalRequest, ...]:
        authorize(principal, "run:inspect", run.project_id)
        current = run.data.get("current")
        return tuple(
            item
            for item in self.requests.values()
            if item.run_id == run.id and item.task_id == current
        )

    async def decide(
        self, run: Inspection, request_id: str, decision: ApprovalDecision, principal: Principal
    ) -> ApprovalRequest:
        authorize(principal, "run:advance", run.project_id)
        request = self.requests.get(request_id)
        if (
            request is None
            or request.run_id != run.id
            or request.task_fingerprint != decision.task_fingerprint
        ):
            raise ValueError("invalid approval identity")
        prior = self.decisions.get(decision.key)
        if prior:
            if prior != (request_id, decision):
                raise ConflictError("decision key reused")
            return request
        if (
            request.task_id != run.data.get("current")
            or request.status != "pending"
            or request.expires_at <= self.clock.now()
        ):
            raise ConflictError("proposal no longer pending")
        request = request.model_copy(
            update={"status": "approved" if decision.decision == "approve" else "denied"}
        )
        self.requests[request_id] = request
        self.decisions[decision.key] = (request_id, decision)
        return request

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
        authorize(principal, "run:inspect", run.project_id)
        suffix = "canary" if phase == "canary" else "experiment"
        if experiment_id != f"{run.id}:{cycle}:{suffix}":
            raise ValueError("fixture identity mismatch")
        item = self.exposures.get(experiment_id)
        now = self.clock.now()
        result = ExperimentSnapshot(
            run_id=run.id,
            cycle=cycle,
            phase=phase,
            experiment_id=experiment_id,
            observed_at=now,
            fresh_until=now + timedelta(seconds=30),
            exposure="unknown" if item is None else "zero" if item["zero"] else "active",
            safety="No native exposure record" if item is None else "Fixture monitor healthy",
            deadline=item["end"] if item else None,
            allocation_percent=(1 if phase == "canary" else 10) if item else None,
            readout="Awaiting mature host readout",
            provenance=[f"fixture:exposure:{experiment_id}"],
        )
        if item is None:
            return result
        if item["zero"] and now >= item["ended"] + timedelta(seconds=2):
            result.readout = "Synthetic readout: inconclusive; retain baseline."
        lower, upper = max(start, item["start"]), min(end, now)
        if upper >= lower:
            count = min(max_points, 30)
            points = [lower + (upper - lower) * i / (count - 1) for i in range(count)]
            result.series = [
                MetricSeries(
                    name="Activation",
                    unit="%",
                    interpretation="Synthetic values; no inference of benefit.",
                    points=[
                        MetricPoint(at=at, value=24 + (i % 7) / 3) for i, at in enumerate(points)
                    ],
                ),
                MetricSeries(
                    name="Error rate",
                    unit="%",
                    guardrail=1,
                    interpretation="Fixture safety threshold",
                    points=[
                        MetricPoint(at=at, value=0.12 + (i % 3) / 20) for i, at in enumerate(points)
                    ],
                ),
            ]
        return result


def create_demo_app(
    *, origin: str = "http://127.0.0.1:8765", bootstrap_token: str | None = None
) -> FastAPI:
    clock = DemoClock(datetime.now(UTC))
    infrastructure = ConsoleFixture(clock)
    base = demo_project(Path.cwd())
    config = replace(
        base, poll_seconds=1, plan=replace(base.plan, canary_min_seconds=8, experiment_seconds=20)
    )
    infrastructure.native_plan = config.plan
    runtime = Runtime(
        ":memory:",
        projects={config.project_id: config},
        runners={"demo": DemoRunner(infrastructure)},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    )
    app = create_manager_app(
        runtime,
        origin=origin,
        bootstrap_token=bootstrap_token,
        approvals=infrastructure,
        metrics=infrastructure,
        demo=True,
        project_labels={"demo": "Activation lab"},
    )
    app.state.runtime = runtime

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await runtime.start(Goal("demo", "Make the first successful action easier"), key="welcome")
        stop = asyncio.Event()

        async def monitor() -> None:
            while not stop.is_set():
                clock.value = datetime.now(UTC)
                infrastructure.monitor()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.25)
                except TimeoutError:
                    pass

        worker = asyncio.create_task(runtime.run_worker(stop, interval=0.25))
        watcher = asyncio.create_task(monitor())
        try:
            yield
        finally:
            stop.set()
            await asyncio.gather(worker, watcher)
            await runtime.close()

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Ephemeral offline ACED manager demo")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    origin = f"http://127.0.0.1:{args.port}"
    app = create_demo_app(origin=origin)
    print(f"Offline fixture only. Open {origin}/#token={app.state.bootstrap_token}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
