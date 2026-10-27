# Embedded runtime

ACED is an async Python library. The host composes one `Runtime`, SQLite store,
identity provider, infrastructure reader and registered agent runners, then explicitly
runs and supervises the worker. There are four `Step` values: `HYPOTHESIZE`,
`IMPLEMENT`, `EXPERIMENT`, and `DECIDE`.

## Run an offline example

For a visual introduction, try the [offline manager demo](manager.md#offline-demonstration).
To see the Python composition directly, install the package using the
[README instructions](../README.md), save the following as `offline_loop.py`, and run
`.venv/bin/python offline_loop.py` from the repository root with the same Python environment:

```python
import asyncio
from pathlib import Path

from aced import Goal, Runtime
from aced.reference import (
    DemoClock,
    DemoIdentity,
    DemoInfrastructure,
    DemoRunner,
    demo_project,
)


async def main() -> None:
    clock = DemoClock()
    infrastructure = DemoInfrastructure(clock)
    runner = DemoRunner(infrastructure)
    project = demo_project(Path.cwd())

    async with Runtime(
        ":memory:",
        projects={project.project_id: project},
        runners={"demo": runner},
        infrastructure=infrastructure,
        identity_provider=DemoIdentity(),
        auth_context=None,
        clock=clock,
    ) as runtime:
        run = await runtime.start(Goal(project.project_id, "Improve activation"), key="trial-1")
        for _ in range(300):
            if run.status in {"completed", "stopped"}:
                break
            run = await runtime.advance(run.id)
            clock.tick()
        if run.status != "completed":
            raise RuntimeError(f"Fixture did not complete: {run.status}; {run.blocker}")
        print(f"{run.status}: {run.cycle} cycles, {len(runner.starts)} tasks")
        print(f"audit valid: {await runtime.store.verify_audit()}")


asyncio.run(main())
```

Expected output:

```text
completed: 2 cycles, 12 tasks
audit valid: True
```

This uses the deterministic fixtures included in `aced.reference`, simulated time
and an in-memory database. It invokes no coding CLI, changes no product, and requires
no credentials. The bounded loop calls `advance` directly to demonstrate progression;
the host-run worker below handles scheduling in an integration. State disappears when
this example exits, so it does not demonstrate recovery across process restarts.

`DemoIdentity` supplies fixture authority and `DemoInfrastructure` supplies synthetic
evidence. They are demonstration components, not authentication or evidence adapters
for a real product. Use the [integration guide](integrations.md) to understand what
your host must supply and the qualification work that remains.

## Host composition

The following sketch assumes the host has supplied a project, registered runners,
infrastructure, identity provider and authenticated context. Unlike the complete
offline example above, it is not a standalone script.

```python
from aced import Goal, Runtime


async def serve(project, runners, infrastructure, identity, auth_context, shutdown):
    async with Runtime(
        "aced-four-stage-v1.sqlite3",  # new file; preserve earlier preview databases
        projects={project.project_id: project},
        runners=runners,
        infrastructure=infrastructure,
        identity_provider=identity,
        auth_context=auth_context,
    ) as runtime:
        run = await runtime.start(Goal(project.project_id, "Improve activation"), key="trial-1")
        await runtime.run_worker(shutdown)
        return await runtime.inspect(run.id)
```

`shutdown` is a host-owned `asyncio.Event`. Signal and join workers before closing
the runtime. Shutdown does not stop product exposure. The independently available
stop executor must remain available throughout worker and agent outages.

## Configuration and authority

`ProjectConfig` requires `project_id`, `workspace`, `source_revision`, `plan`, and
nonempty product-specific `required_checks`. Supply a stable physical `resource_id`
for the shared product (default: resolved workspace), default runner, optional
`steps: Mapping[Step, StepConfig]`, constraints, `max_tasks`, `max_attempts`,
`max_cycles`, `cleanup_tasks`, `poll_seconds` and `approvals: ApprovalPolicy`.
Separate project IDs sharing the same resource cannot own concurrent nonterminal
runs, including held or stopping runs. Hosts sharing a product must also share the
ownership database or enforce exclusive ownership externally; separate SQLite files
are not distributed leases.

`StepConfig` selects an optional runner, actual instruction content, prepared tool
profile, `timeout_seconds` and host-enforced `max_cost`. Instructions, runner, scope,
inputs and deadline are frozen per task. Routing/instruction changes apply only to
future tasks. Source/workspace, plan template and `plan_bounds`, constraints, checks,
authority metadata and budgets remain frozen for the run. Keep original runner
registrations available for recovery. Hypothesize accepts a complete host-approved
cycle plan within `PlanBounds`; no bounds means the exact configured plan. The accepted
`cycle_plan` is immutable through implementation, exposure, decision and repair.
`next_hypothesis` permits a newly approved plan for the next cycle.

Set `require_research_observation=True` when research requires a host-captured
snapshot. Core waits before task preparation until an authenticated
`record_observation` supplies its reference; the host must validate the retained
snapshot's content, freshness and run/cycle/source scope before recording and again
before launch. This flag is frozen with the run. A new hypothesis clears the prior
cycle's reference; repair retains the original context. Generic hosts default to
`False`. Missing-input recovery for an already completed task uses existing bounded,
host-authorized correction, retaining the original task and output unchanged.

`ExperimentPlan` supplies metric/rule, separate canary/main cohorts and allocations,
canary traffic and duration bounds, fixed main duration, `monitor_grace_seconds`,
guardrails, readout delay and promotion observation duration. There is no agent
health interval. `native` retains product-specific policy details without a provider
catalogue or serialized configuration loader.

`ApprovalPolicy` specifies `boundaries` (review, deny or preauthorized), authenticated
`approvers`, existing `channel`, `notification_destinations`, preferred `events`,
`delivery_failure`, `no_response`, `no_response_seconds`, `validity_seconds` and
`escalation`. Unspecified scopes require review. The separately maintained
[playground host](integrations.md#example-availability) implements a local
approval/event inbox and rejects unsupported connections. That host is not included
in this package. Your host supplies its existing notification connection; no
messaging provider is bundled.

`Runtime` defaults to a 60-second lease and a 30-second timeout per host call. Set
`host_timeout_seconds` below `lease_seconds`, and allow enough total lease time for
all calls and persistence in an advance. Expired or superseded workers cannot commit;
leases do not renew themselves. Native exposure deadlines and task deadlines are
separate. Credentials never belong in persisted task context.

## Public operations

| Async method | Behavior |
| --- | --- |
| `start(goal, key=..., continuation=None)` | Create or recover the same named goal; optionally bind selected verified learning/backlog from a closed run |
| `list_runs(project_id, limit=100, after=0)` | Authorized discovery with exclusive creation-event cursors and inspection redaction |
| `inspect(run_id)` | Current stage, scope, task metadata, control, blocker, wake, revision and authorized context; raw result omitted |
| `history(run_id, limit=100, after=0)` | Paginated compact audit events; `after` is the returned event sequence |
| `tasks(run_id, limit=100, after=0)` | Paginated retained inputs, results and metadata; `after` is task sequence |
| `advance(run_id)` | Common bounded progression path used by the worker |
| `hold(run_id)` / `resume(run_id)` | Hold ordinary scheduling; resume rechecks safety and preserves stopping |
| `stop(run_id)` | Persist sticky operator intent, deliver the independent stop request, then reconcile |
| `repropose(run_id)` | Replace only an unlaunched task proposal, release its reservation, require new approval |
| `record_observation(run_id, reference)` | Authenticated, coalesced wake hint; reread authoritative facts |
| `run_worker(stop_event, interval=1.0)` | Poll due work under host supervision |

The identity provider authenticates context into `Principal`; caller-supplied names
are not identity. Claims require the operation (`run:create`, `run:inspect`,
`run:advance`, `run:hold`, `run:resume`, `run:stop`, `run:repropose`, `run:observe`)
and `project:<id>`. `run:*` and `project:*` are broad grants. An authenticated
`run:stop` principal can deliver the frozen independent-stop request without the
ordinary worker lease or retained-evidence read claims. Subsequent cancellation and
reconciliation still need advancement authority and the required evidence access.
Inspection is redacted
when evidence claims are missing; history, task reads and advancement require them.

## Waiting, recovery and stopping

A completed invocation is stored once. A native wait rechecks the same immutable
output without another model call. A verified same-stage engineering increment may
yield a timer and later receive a fresh invocation. Unchanged waits, authorization
expiry renewals and coalesced wake hints do not append history. Host exceptions retain
bounded exception type and an actionable protected-diagnostic pointer, not raw secrets.
The worker uses a local monotonic throttle at the run's frozen `poll_seconds` for
all nonterminal runs, including future native-evidence waits, without extra database
writes or model invocations. A meaningful safety incident therefore does not wait for
the experiment deadline. A changed revision or an
authenticated wake hint bypasses that throttle; restart may perform one immediate
cheap recheck. Explicit `advance` remains eager.

Preparation reserves invocation capacity; first dispatch consumes it once. Uncertain
launch counts once, and recovery observes `ExecutionRef(task.id, task.id)`. Observing
an execution or awaiting approval consumes no extra invocation. Rejected output
requires host-confirmed settled effects and `correction_safe` before a reporting-only
correction; each correction consumes ordinary and correction budgets. Budget exhaustion
and denial remain nonterminal blockers. No response is a durable wait. An expired
unlaunched proposal can be explicitly replaced with `repropose`; its old approval
cannot authorize the new fingerprint.

Hold permits acceptance of finished facts but prevents ordinary launch or resumption.
Safety work continues. Stop delivery precedes cancellation and retries retain one
request identity. Acknowledgment, applied protection, effective zero and execution
settlement are distinct facts. Old work must be terminal or authoritatively fenced
before a same-stage `purpose="reconcile"` invocation receives cleanup authority.
Cleanup agent execution has its own finite allowance. Evidence-only settlement is
attempted before reserving capacity and remains available after that allowance is
exhausted; a reservation proven never dispatched is released. If actual cleanup work
needs unavailable authority or capacity, the run remains visibly stopping.

A safely settled operational failure may reach Decide and explicitly authorized repair;
operator stop cannot. Repair retains hypothesis/plan/baseline and failure learning,
with fresh identities and checks. Normal completion requires settled disposition,
retained source, learning and assessment. Safely stopped runs may retain an explicit
`learning_unavailable` gap when learning cannot be obtained.

A settled historical incident stays in the evidence without repeatedly triggering
cleanup. Read-only Decide can proceed after verified zero and effect settlement.
New observed exposure or a new capable invocation restores the stop obligation.
Fresh positive exposure after confirmed zero restores it even when healthy and
identity-matched. The new obligation has a fresh stop request; the previous request
and receipts remain in history. Stale pre-closure reports and actual authorized
promotion observation do not count as new unexpected exposure.

For a new goal, pass `RunContinuation(previous_run_id, accepted_source,
learning_references=..., candidate_ids=...)`. Each selection is bounded to 32 entries.
Core verifies terminal settlement, the same resource and exact configured/accepted
source, authenticates the prior evidence claims, and derives the selected records
from the stored history. The frozen handoff includes prior revision/digest lineage;
no caller-supplied transcript or invented learning is accepted.

## Storage

New databases use marker `cddai-four-stage-1`; the ACED rename preserves existing
databases with that format. Earlier schemas are rejected, never migrated. Use a
fresh database for those earlier previews and preserve their matching code and
records; do not initialize this Runtime to inspect an earlier-format store.

Current run projections, task outbox/metadata, immutable content records and compact
audited events are separate tables in one transaction. Inputs/results are immutable;
active projections bind their digests to the committing event. Reopen validates format,
indexed current run/task projections (including terminal run status) and tail anchors; `await runtime.store.verify_audit()`
performs the full historical scan. This is accidental-corruption detection, not a
replacement for protected storage or consistent backups of native receipts/job records.

See the [isolated persistence measurement](designs/four-stage-orchestration.md#isolated-persistence-measurement) for measured storage growth and the
[roadmap](roadmap.md) for live qualification still required.

The optional [local manager](manager.md) exposes these operations in a browser.
The host continues to own runtime and worker supervision.
