"""Reopen SQLite after a lost launch response, while the fixture host stays alive."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from aced import Goal, Runtime, Step
from aced.reference import DemoClock, DemoIdentity, DemoInfrastructure, DemoRunner, demo_project


async def demonstrate(directory: Path) -> None:
    clock = DemoClock()
    infrastructure = DemoInfrastructure(clock)
    runner = DemoRunner(infrastructure)
    runner.lose_start_response = True
    project = demo_project(directory)
    database = directory / "runtime.sqlite3"
    goal = Goal(project.project_id, "Improve activation")

    # These fixture adapters deliberately stay alive across the Runtime reopen.
    # A real host must retain its own execution and product records independently.
    async with Runtime(
        database,
        projects={project.project_id: project},
        runners={"demo": runner},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        run = await runtime.start(goal, key="lost-launch-response")
        interrupted = await runtime.advance(run.id)
        original_task = interrupted.data["task"]["task"]
        original_stored_task = (await runtime.tasks(run.id))[0]["task"]
        assert "unknown" in (interrupted.blocker or "")
        assert len(runner.starts) == 1
        print("Launch response lost: outcome unknown; 1 fixture invocation")

    async with Runtime(
        database,
        projects={project.project_id: project},
        runners={"demo": runner},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        reopened = await runtime.start(goal, key="lost-launch-response")
        assert reopened.id == run.id
        assert reopened.data["task"]["task"] == original_task
        print("SQLite reopened: same run and frozen task")

        recovered = await runtime.advance(run.id)
        assert recovered.step is Step.IMPLEMENT
        assert runner.starts == [original_task["id"]]
        assert runner.observations == 1
        assert recovered.data["task_count"] == 1
        retained = await runtime.tasks(run.id)
        assert len(retained) == 1 and retained[0]["task"] == original_stored_task
        assert retained[0]["result"]["status"] == "completed"
        assert await runtime.store.verify_audit()
        print("Original execution observed: completed; 0 duplicate launches")
        print("Next stage: implement; audit valid: True")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="aced-resume-") as temporary:
        asyncio.run(demonstrate(Path(temporary)))
