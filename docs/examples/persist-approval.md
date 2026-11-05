# Preserve a human-approval wait across process restarts

An approval wait should survive the process that requested it. This example runs
two separate Python child processes against one temporary SQLite database. The
second recovers the same run, task, fingerprint and authorization reference, keeps
waiting without launching an agent, then simulates the host approving that task.

From a source checkout with Python 3.12+, install the core and run:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/persist_approval.py
```

Expected output:

```text
Process 1 exited: approval waiting; 0 launches
Process 2: same run, task, fingerprint and authorization reference
Still waiting: 0 launches; unchanged revision
Simulated host approval: original task launched once; audit valid: True
```

The [complete script](../../examples/persist_approval.py) first asks the fixture
host for authorization. The host returns `WAITING`; ACED persists the proposal and
wait without consuming an invocation. That child process exits and closes SQLite.
The parent launches a new child and passes only the four identity values used for
comparison. The run, frozen task and authorization are recovered from the database.

The new process reconstructs the fixture adapters and authenticates through
`DemoIdentity`. An unchanged approval wait adds no revision and causes no launch.
The example then changes the fixture host response to `ALLOWED` and checks that
exactly the original task is launched once. The accepted result reaches Implement;
the script ends before implementation or exposure and removes its temporary files.

This persists a **pending approval**, not a real person's decision or an external
approval service. Approval is rechecked against the host after restart. Both
processes use simulated time, and no launched operation needs recovery between
them. `DemoIdentity` and `DemoInfrastructure` provide synthetic authority; a real
host must authenticate its approvers and retain its own approval records. No
credentials, coding CLI, product changes or network are involved.

For human approval in an integration, configure host-owned approval boundaries
and supply the corresponding adapter. See [configuration and authority](../runtime.md#configuration-and-authority)
and the [integration guide](../integrations.md). The preview is not qualified for
production credentials, real users or unattended operation.
