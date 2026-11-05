# Resume an agent workflow after a lost launch response

When a launch response is lost, starting the task again may duplicate work. ACED
retains the original task intent in SQLite and observes its execution on recovery.
This example reopens the coordinator after that uncertainty and checks that the
original task completes with exactly one invocation.

From a source checkout with Python 3.12+, install the core and run:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/resume_workflow.py
```

Expected output:

```text
Launch response lost: outcome unknown; 1 fixture invocation
SQLite reopened: same run and frozen task
Original execution observed: completed; 0 duplicate launches
Next stage: implement; audit valid: True
```

The [complete script](../../examples/resume_workflow.py) creates a fresh temporary
SQLite database, simulates a successful fixture execution whose launch response
is lost, and closes the `Runtime`. A new `Runtime` opens the same database and
recovers the named goal, frozen task and original result. It checks the retained
task payload, invocation count and audit history before removing its temporary
files. It stops after accepting research, before implementation or exposure.

The fixture runner and host ledger remain alive in the **same Python process**.
This demonstrates coordinator reopen and uncertain-launch reconciliation; it does
not demonstrate recovery after a whole-host crash or loss of native execution
records. `DemoInfrastructure` and `DemoRunner` are in-memory fixtures. A real
integration must independently retain execution receipts and authoritative product
records so the reopened coordinator can observe what actually happened.

No coding CLI, credentials, network, product changes or traffic are involved.
`DemoIdentity` supplies fixture authority, not real authentication. Development
preview checks do not qualify production or unattended operation.

See [waiting and recovery](../runtime.md#waiting-recovery-and-stopping) for the
runtime contract, [host integration](../integrations.md) for responsibilities, and
the [two-process approval example](persist-approval.md) for a process exit before
any task is launched.
