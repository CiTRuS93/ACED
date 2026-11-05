"""Run two deterministic product-experiment cycles without agents or traffic."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from aced import Goal, Runtime
from aced.reference import DemoClock, DemoIdentity, DemoInfrastructure, DemoRunner, demo_project


async def demonstrate(directory: Path) -> None:
    clock = DemoClock()
    infrastructure = DemoInfrastructure(clock)
    runner = DemoRunner(infrastructure)
    project = demo_project(directory)

    async with Runtime(
        directory / "runtime.sqlite3",
        projects={project.project_id: project},
        runners={"demo": runner},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        run = await runtime.start(Goal(project.project_id, "Improve activation"), key="two-cycles")
        previous = None
        for _ in range(300):
            position = (run.cycle, run.step.value, run.data["scope"])
            if position != previous:
                print(f"Cycle {position[0]}: {position[1]} / {position[2]}")
                previous = position
            if run.status in {"completed", "stopped"}:
                break
            run = await runtime.advance(run.id)
            clock.tick()  # Advance synthetic time; no wall-clock experiment wait.

        if run.status != "completed":
            raise RuntimeError(f"Fixture did not complete: {run.status}; {run.blocker}")
        assert run.cycle == 2 and len(runner.starts) == 12
        assert len(set(runner.starts)) == 12
        assert len(run.data["learning"]) == 2
        assert run.data["retained_source"] == "source-2"
        for cycle in (1, 2):
            canary = infrastructure.exposures[f"{run.id}:{cycle}:canary"]
            main = infrastructure.exposures[f"{run.id}:{cycle}:experiment"]
            assert canary["zero"] and main["zero"]
            assert canary["ended"] <= main["start"]
        next_research = next(
            task for task in runner.tasks.values() if task.cycle == 2 and task.step == "hypothesize"
        )
        assert next_research.context["source_baseline"] == "source-1"
        assert len(next_research.context["learning"]) == 1
        assert await runtime.store.verify_audit()
        print("Completed: 2 cycles; 12 fixture tasks; 2 retained learning records")
        print("Each canary reached zero before its separate main experiment")
        print("Cycle 2 received source-1 and prior learning; retained source: source-2")
        print("All fixture experiments closed; audit valid: True")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="aced-experiment-") as temporary:
        asyncio.run(demonstrate(Path(temporary)))
