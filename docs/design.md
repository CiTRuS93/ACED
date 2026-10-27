# Design: four stages, durable handoffs

This page describes the implemented development preview. The
[four-stage design](designs/four-stage-orchestration.md) retains its rationale and
acceptance criteria; [the state chart](designs/aced-state-chart.md) expands its
conditions. Fixture coverage is not evidence of a successful live cycle or
production, real-user, supervised persistent, or unattended qualification.

![Four-stage orchestration and responsibilities](images/four-stage-orchestration.png)

[Full-size PNG](images/four-stage-orchestration.png) · [Editable SVG](images/four-stage-orchestration.svg)

The [class diagram](code-structure.md) maps these responsibilities to the current
core, playground host, native product and private operator components.

## Responsibilities

ACED owns **Hypothesize → Implement → Experiment → Decide → Repeat**: legal
transitions, immutable task intent, runner selection, budgets, waits, approvals,
evidence acceptance, stopping/reconciliation, accepted source and learning. One
coordinator, one transition registry, one SQLite store and one durable task outbox
serve both foreground advancement and the host-run worker.

Agents own research, coding, test/debug loops, instrumentation, use of existing
release/experiment tools, diagnosis, interpretation and authorized disposition.
Several engineering increments can remain inside one Implement stage. Separate
real experiments are separate complete learning cycles.

The host owns authenticated identity, credentials, isolation, actual tool scope,
approvals, trusted checks, authoritative product records, statistics, delivery,
exposure controls, independent monitoring/stopping, external-operation idempotency
and process supervision. `authorize`, `read_evidence`, `safety` and `request_stop`
are the small async infrastructure interface. The reader translates native records;
it does not repeat agent procedures or choose stages. Prompt text is not permission.

## Stage handoffs

| Stage | Accepted handoff |
| --- | --- |
| Hypothesize | Retained candidates with stable IDs and rationale; selected hypothesis and research reference; accepted frozen plan |
| Implement | Exact candidate/artifact, required trusted checks, and verified observability instructions and references |
| Experiment | Actual closure and mature native analysis, or verified settled unsuccessful attempt |
| Decide | Settled disposition, retained source, evidence-linked learning, goal assessment and authorized `next_hypothesis`, `repair` or `finish` |

Research retains claims, evidence, assumptions, expected learning, effort/risk,
dependencies and selection/defer/rejection rationale. An existing tracker or
versioned artifact carries this work across conversations. Linked phases retain a
parent initiative, phase ID, dependencies and continuation criteria; earlier
learning can cancel later phases. ACED manages the selected cycle, without a
campaign workflow or universal prioritization score.

Typed `ProjectConfig` supplies a plan template and optional `PlanBounds` defining
the immutable run authority. Hypothesize may propose a complete different plan
within those bounds; the host approves the exact proposal and core freezes it for
that cycle before Implement. Omitting bounds restricts research to the configured
fixed plan. A materially changed plan requires a new Hypothesize cycle. Repair
keeps the accepted hypothesis, plan and baseline and repeats fresh checks/canary.

When the host requires a scoped research observation, it sets
`require_research_observation=True`. Core waits before reserving or freezing a
Hypothesize task until the host records its verified reference. A new hypothesis
cycle clears the previous observation; repair preserves the original research
context. The host validates content, freshness, run/cycle/source and native zero.
Already completed missing-input tasks retain their original inputs and output;
host-verified safe correction uses a newly authorized, budgeted task.

An explicit `RunContinuation` binds a new goal to a safely closed run, its exact
accepted source and selected retained learning/candidates. Core authenticates access
to that previous evidence, verifies resource/source lineage, and passes the selected
records and their references to the next Hypothesize task without copying transcripts.

Implementation checks instrumentation in its authorized test environment:
normal/failure signals, useful queries, missing/stale-data interpretation,
monitoring instructions and the frozen guardrails. Experiment verifies actual
serving identity, readiness and telemetry after disabled deployment and before
exposure. Raw telemetry stays in existing systems. No errors without traffic or
telemetry does not establish health; health does not establish product benefit.

## Consequential boundaries

A checked candidate precedes deployment/exposure. The bounded operational canary
must close to confirmed zero before a separate fixed-allocation main experiment
with excluded canary participants and its own window. The native first-allocation
receipt establishes one authoritative exposure deadline. Lost responses cannot
renew it; observe the original execution/operation.

A task ends before its authority expands to `main_exposure` or `disposition`.
Each new immutable task receives current host authorization. `ApprovalPolicy`
configures review, denial or scoped preauthorization by boundary, authenticated
approvers, an existing channel, notification destinations/events, and delivery,
no-response and escalation behavior. An acknowledgment or arbitrary message is
not approval. No response remains a durable wait without a running agent. Host
command permissions and independent stopping remain effective during that wait.

Normal expiry requests closure evidence; coordinator/monitor ordering cannot turn
it into a failed experiment. Actual zero and readout maturity are separate guards.
Unknown activation can resolve to a protected experiment still running under its
original deadline. Sustained monitoring failure, harm or invalid identity follows
the independent stop and reconciliation path. There is no periodic HEALTH agent.

Independent stopping remains mandatory throughout exposure. The host defines safety
triggers before exposure, including thresholds, observation windows and missing-data
rules. An ambiguous or nonwinning business result alone does not trigger emergency
stopping or shorten the planned experiment. It proceeds to mature readout and Decide;
operational safety triggers and authorized stop requests still take precedence.
Positive experiment exposure beyond the original deadline and bounded closure grace
requires stopping even when reported healthy. Authorized promotion has its own
observation and protection obligations.

Promotion requires disposition authority, independent delayed-harm protection,
separately available rollback and completed observation. Normal completion requires
settled effects, retained source and learning. `attained`, `not_attained` and
`undetermined` describe goal assessment separately from run or experiment outcomes.

## Holds, stopping and recovery

Hold blocks ordinary new launches, including resumed/corrective/repair work.
Already completed output and verified facts may be recorded and advance the stage
while hold remains set. This preserves observed reality without starting work.
Safety observation, stop delivery and bounded reconciliation continue.

Stop first persists sticky intent and one stable request ID, then delivers to the
existing independent executor before or alongside cancellation. Delivery
acknowledgment is not effective zero. Reconciliation requires terminal execution
or authoritative fencing, actual effect settlement, prevention of late
re-exposure, required rollback and verified retained source. Uncertainty stays
nonterminal. Shutdown or cancellation does not stop product exposure.

Fresh unexpected positive exposure after confirmed zero creates a new stop
obligation even if the host reports healthy matching identities. Prior settlement
does not suppress it. Core preserves the earlier stop receipt/history, resets
cached closure, and blocks ordinary work until fresh reconciliation. A stale
pre-closure report is not new exposure. Actual authorized promotion observation
remains distinct from re-exposure; a proposal or rollback task is not that authority.

Ordinary budget exhaustion, correction limits and denial are named nonterminal
blockers. An authenticated operator can resolve the dependency or explicitly stop;
there is no automatic abandonment or invented terminal failure. A separate finite
cleanup allowance preserves necessary reconciliation. Safely stopped runs may
retain `learning_unavailable` with a factual reason; normal completed cycles and
repair may not omit learning.

## Persistence and identity

Public operations are async and principal-bound. Reauthorize resource scope and
retained evidence claims on access; caller names are not identity. Host calls run
outside SQLite write transactions. Revisions and expiring fences prevent stale
workers from committing.

Use a fresh database with format **`cddai-four-stage-1`**. Earlier preview stores
are rejected without migration. Preserve their original code, databases, receipts
and transcripts; never initialize this runtime against historical production data.

`runs` holds the current compact projection; `tasks` retains each immutable intent
and current execution metadata; `records` stores inputs, results and verified
handoffs by content digest; `events` holds ordered changed fields and references.
A completed result is retained once. Unchanged saves append no event. Task/result
content is immutable; projection digests are atomically bound to committing events.
Ordinary reopen verifies format, tail/order anchors, run projections and referenced
current tasks/records. It does not scan historical task/event content. Explicit
`verify_audit()` verifies the complete retained history. `history()` and `tasks()`
use bounded pages with exclusive integer `seq` cursors.

Canonical JSON/hashing lives only in `aced._json`; timestamps use aware UTC. Back
up the database and referenced host records together. Digests do not replace
retained accessible content. One nonterminal run owns each project and each
`resource_id` through held/stopping cleanup; different project IDs cannot hide a
shared shop. All contenders must use the same authoritative store: distributed
ownership between independent databases remains outside this preview.

## Deliberate limits

Typed host Python composition is the configuration entry point. Alternate stores,
serialized configuration loaders, vendor discovery, SDK dependencies, messaging
platforms, remote dashboards, hosting, allocation ramps, general remediation and a second
workflow engine remain deferred. Optional scheduled bounded proposal discovery can
use existing research tools with read-only product access, proposal-write access
and a separate budget; the sequential runtime does not schedule concurrent research.

See [integration](integrations.md), [runtime](runtime.md),
[onboarding](designs/new-user-onboarding.md) and the [qualification roadmap](roadmap.md).

## Local operator console

The optional [manager](manager.md) serves a packaged React UI over an
ASGI adapter that defaults to loopback and permits explicit host-configured LAN
access. It reuses the single coordinator and store, with project-scoped run
discovery and host-owned approval/metric adapters. Browser polling never advances
the lifecycle; host workers and independent stopping remain available separately.
Scheduling state and host exposure state are displayed separately. Missing or stale
telemetry cannot establish safety, success, or effective zero.
