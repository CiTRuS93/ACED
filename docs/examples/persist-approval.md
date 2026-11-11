---
title: Preserve human approval waits across process restarts
description: Use a two-process SQLite fixture to preserve a pending approval, then check host authorization and task identity when a workflow remains blocked.
---

# Preserve a human-approval wait across process restarts

An approval wait should survive the process that requested it. This example runs
two separate Python child processes against one temporary SQLite database. The
second recovers the same run, task, fingerprint and authorization reference, keeps
waiting without launching an agent, then simulates the host approving that task.

From a source checkout with Python 3.12+, install the core and run. These commands
use the POSIX virtual-environment path; see the [first-run checklist](../README.md#first-run-checklist)
for prerequisites and the Windows interpreter path:

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

## If approval does not release your own run

Use the host's authenticated inspection and approval interface to check the
**current frozen proposal**, not just the human-readable goal. ACED does not bundle
an approval inbox or notification provider for your product. The [local manager](../manager.md)
exposes a host adapter; its offline demo is not that adapter for a real product.

| What you observe | What to check next |
| --- | --- |
| The same proposal is still waiting after restart | This is expected until the host returns valid authorization. Check delivery and the host's approval record; restarting does not approve it. |
| A person approved, but no task launches | Verify the authenticated approver, task fingerprint, requested scope and validity in the host record. Also inspect holds, task deadlines and the current blocker. Do not widen permissions just to make it run. |
| Approval is denied or no response arrives | Keep the blocker or wait visible. Denial and no response do not grant permission; resolve them through the configured host policy. |
| An unlaunched proposal has expired or needs replacement | An authorized caller can use `Runtime.repropose(run_id)`. The replacement needs fresh approval; the old decision cannot authorize its new fingerprint. |
| A task has already launched, or its launch outcome is unknown | Do not repropose or launch again. Follow [original-execution recovery](resume-workflow.md#if-your-own-run-is-still-waiting). |

Host approval must cover the actual task and tool scope. It does not make ACED an
interceptor for every tool call or permit effects outside the host's authorization.
Do not copy the fixture's `infrastructure.approval = ApprovalStatus.ALLOWED` into a
real approval flow: that assignment simulates a decision and authenticates nobody.

Continue with [configuration and authority](../runtime.md#configuration-and-authority)
for approval policy and [public operations](../runtime.md#public-operations) for
caller claims. If a pending approval appears to require another model invocation,
compare it with this fixture's unchanged revision and zero launches before changing
runtime behavior.
