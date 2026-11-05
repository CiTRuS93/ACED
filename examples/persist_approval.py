"""Preserve a pending approval across two Python processes, before any launch."""

import asyncio
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from aced import ApprovalStatus, Goal, Runtime, Step
from aced.reference import DemoClock, DemoIdentity, DemoInfrastructure, DemoRunner, demo_project


async def phase(database: Path, expected: list[str]) -> None:
    clock = DemoClock()
    if expected:
        clock.tick(10)
    infrastructure = DemoInfrastructure(clock)
    infrastructure.approval = ApprovalStatus.WAITING
    runner = DemoRunner(infrastructure)
    project = demo_project(database.parent)

    async with Runtime(
        database,
        projects={project.project_id: project},
        runners={"demo": runner},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        run = await runtime.start(Goal(project.project_id, "Improve activation"), key="approval")
        if not expected:
            run = await runtime.advance(run.id)
        original = run.data["task"]
        authorization = original["authorization"]
        identity = [
            run.id,
            original["task"]["id"],
            authorization["task_fingerprint"],
            authorization["reference"],
        ]
        assert authorization["status"] == "waiting"
        assert run.data["task_count"] == 0 and not runner.starts
        assert await runtime.store.verify_audit()

        if not expected:
            # The parent carries only these comparison values into the next
            # process. Run state, task intent and authorization are read from SQLite.
            print(" ".join(identity))
            return

        assert identity == expected
        waiting = await runtime.advance(run.id)
        assert waiting.revision == run.revision and not runner.starts
        print("Process 2: same run, task, fingerprint and authorization reference")
        print("Still waiting: 0 launches; unchanged revision")

        # Simulate a host approval arriving. This is not a real human approval
        # adapter: DemoIdentity and DemoInfrastructure provide fixture authority.
        infrastructure.approval = ApprovalStatus.ALLOWED
        launched = await runtime.advance(run.id)
        assert runner.starts == [expected[1]]
        assert runner.tasks[expected[1]].fingerprint == expected[2]
        assert launched.data["task"]["authorization"]["status"] == "allowed"
        assert launched.data["task"]["authorization"]["reference"] == expected[3]
        accepted = await runtime.advance(run.id)
        assert accepted.step is Step.IMPLEMENT
        assert await runtime.store.verify_audit()
        print("Simulated host approval: original task launched once; audit valid: True")


def main() -> None:
    if len(sys.argv) > 1:
        # Internal child invocation; the documented command needs no arguments.
        database, expected = Path(sys.argv[1]), sys.argv[2:]
        # Refuse an existing database in phase one, or a missing one in phase two.
        if len(sys.argv) not in {2, 6} or database.exists() != bool(expected):
            raise RuntimeError("Unexpected database state for the requested example phase")
        asyncio.run(phase(database, expected))
        return

    with TemporaryDirectory(prefix="aced-approval-") as temporary:
        database = Path(temporary) / "runtime.sqlite3"
        command = [sys.executable, str(Path(__file__).resolve()), str(database)]
        first = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        expected = first.stdout.strip().split()
        if len(expected) != 4:
            raise RuntimeError("First process did not return its frozen proposal identity")
        print("Process 1 exited: approval waiting; 0 launches", flush=True)
        subprocess.run([*command, *expected], check=True, timeout=30)


if __name__ == "__main__":
    main()
