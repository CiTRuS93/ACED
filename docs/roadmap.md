# Qualification roadmap

The maintained scope is an embedded, agent-neutral loop with SQLite and Codex,
Claude Code, Cursor and OpenCode CLI runners. Host infrastructure supplies existing
development and product tools. Additional runners use the same interface; a vendor platform or
multi-agent framework is not required.

The current package is a **development preview**. Deterministic conformance and
regression tests do not qualify production credentials, real-user exposure,
supervised persistent operation, or unattended operation.

## Implemented contract versus live qualification

The package implements the durable coordinator, task records, per-step routing,
built-in CLI adapters, explicit authority boundaries, retained research candidates and phases,
observability handoffs, compact audited persistence and the four-stage learning cycle.
Tests use deterministic agents and infrastructure fixtures to exercise the loop and
its failure behavior. No live provider account or production product is implied.
The playground also tests the installed native sandbox with a fake CLI, including
trusted check/protection requests, protected recorder files, public-only candidate
snapshots and Git history. That is actual sandbox-path evidence without a model or
credentials; it does not establish a live learning cycle.

A separate [playground integration snapshot](playground-example.md) records real
Codex execution reaching a main experiment on a synthetic storefront, following
an interrupted first attempt and a repair cycle. Its readout and disposition are
still pending at that snapshot. This is partial live adapter evidence; it does
not establish a completed measured cycle or operational qualification.

A host integrating a real product must qualify the following before stronger
profiles can be enabled:

| Area | Required evidence |
| --- | --- |
| Agent execution | Each selected CLI version, output handling, permission denial, timeout/cancellation, restart identity, and isolated tool access |
| Identity and authority | Scope enforcement, expired/revoked decisions, changed inputs, protected verifier configuration, and secret redaction |
| Verification and delivery | Exact checked source/artifact, disabled deployment, promotion, rollback, and observable outcomes |
| Experimentation | Instrumentation, assignment, canary/experiment separation, carryover treatment, validity, maturity, and native decisions |
| Independent stopping | Effective-zero measurements during controller/model outages; separately confirmed rollback |
| Persistence | Competing workers, crash recovery, uncertain effects, backup/restore, and audit reconstruction |
| Full journey | Two complete cycles with accepted-source/learning continuity, including failed and inconclusive paths |

Do not change qualification policy merely because a happy-path demo passed.
Operational evidence belongs to the actual host environment and selected versions.

## Next integration work

1. Qualify the supplied runner profile with an actual model/account in a separately
   authorized isolated environment.
2. Configure a disposable shop to serve the exported public product workspace and
   verify the supplied authorization, tool and evidence connections with its real records.
3. Run the complete four-stage journey through canary/zero/main/zero, disposition and retained learning.
4. Exercise faults and outages, especially uncertain launch and emergency stopping.
5. Independently review the evidence before admitting production or unattended profiles.

## Deferred

Alternate stores, distributed coordination, dynamic provider discovery, multiple
agents collaborating within one task, general workflow editing, remote team dashboards, hosting,
serialized configuration, allocation ramps/rebalancing, and general remediation
engines require a separate product decision. A new runner is justified by an actual
integration, not by a speculative abstraction.

ACED implements the Continuous Data-Driven AI Development paradigm. The broader
paradigm does not establish that every level of autonomy ships or is safe to enable.

## Explicit remaining extensions

Agent-selected cycle plans within frozen host bounds and verified cross-run learning
handoffs are implemented. The playground supplies a local approval/event inbox;
external notification providers remain host connections. Existing trackers may retain
proposals, but core does not schedule concurrent research. Optional scheduled discovery,
richer approval connections and additional runners require a concrete consumer.

Long-run context compaction is also deferred. The current runtime passes accumulated
learning and candidate outcomes into later task inputs; its finite frozen run budgets
bound growth, but doubling many-cycle workloads is not approximately linear. See the
[fixed-payload and multi-cycle measurements](designs/four-stage-orchestration.md#isolated-persistence-measurement).
Before increasing those budgets for long-running work, retain full learning in
referenced records/artifacts and pass bounded recent summaries to future tasks.
Preserve exact prior experiment/canary identity guards and access to the full retained
evidence. Core defaults are 10 cycles/100 tasks; playground defaults are one cycle/40
tasks. Fixture completion does not establish live or operational qualification.

## Local manager qualification

The optional local console and offline demo now cover run management, approval
review and host-provided metric charts. API, component and browser fixture checks
do not qualify a real approval/metrics connection, remote access or unattended
operation. Qualify each host adapter with its authoritative records and revoked
identity/expired-decision cases before relying on it in a live integration.
