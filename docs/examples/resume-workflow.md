---
title: Recover an agent workflow after a lost launch response
description: Use an offline SQLite fixture to reconcile a lost agent launch response, then diagnose unknown outcomes without blindly launching a replacement.
---

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

## If your own run is still waiting

This is an integration checklist, not another standalone fixture command. Inspect
the existing run through an authenticated host using `Runtime.inspect(run_id)`.
Use `Runtime.tasks(run_id)` and `Runtime.history(run_id)` only with the required
evidence-read claims. Retain those records privately; inspection can be redacted.

| What you observe | What to check next |
| --- | --- |
| Launch outcome or original execution is unknown | Keep the original task identity and runner registration. Restore the host's execution lookup so recovery can observe the original execution; do not manually launch a replacement. |
| An agent finished, but the stage has not advanced | Check the blocker and host evidence for the frozen task, source and scope. Agent completion alone is not accepted product evidence. |
| The run is held | A hold prevents ordinary scheduling, not safety work or exposure. An authorized `resume` rechecks safety; it is not a replacement launch. |
| The run is stopping | Keep the independent stop executor available and reconcile confirmed zero exposure and settled effects. Closing the runtime or receiving a stop acknowledgment does not prove either. |
| Opening SQLite reports an incompatible format | Preserve the original database and its matching code. Do not rewrite its marker or create a new database to continue uncertain external work. See [storage compatibility](../runtime.md#storage). |

Recover using the same database and run identity, registered original runner and
independently retained host records. Do not use a new goal key, empty database,
or `repropose` to bypass a launched task with an unknown outcome. `repropose` only
replaces an **unlaunched** proposal and requires fresh approval. If native records
cannot establish what happened, leave the uncertainty visible and resolve it with
the host rather than treating absence of evidence as a safe retry.

The [runtime recovery contract](../runtime.md#waiting-recovery-and-stopping)
describes worker supervision and reconciliation. A SQLite reopen and a valid audit
cannot establish external execution settlement, whole-host crash recovery or
product safety on their own.
