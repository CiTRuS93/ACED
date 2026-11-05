# Documentation

The root [README](../README.md) describes the shipped development preview. These
guides explain its responsibilities, host contract, and qualification limits.

## Start here

1. [Try the offline manager demo](manager.md#offline-demonstration) to review approvals,
   follow experiment observations and inspect retained learning in a local browser.
2. [Run a complete Python example](runtime.md#run-an-offline-example) to compose the
   runtime with the included deterministic fixtures.
3. Try the runnable guides for [workflow recovery](examples/resume-workflow.md),
   [approval waits across restarts](examples/persist-approval.md), and a
   [synthetic experiment with retained learning](examples/synthetic-experiment.md).
4. [Integrate a product](integrations.md) when you are ready to supply host identity,
   tools, authoritative evidence and independent stopping.

The offline examples require no coding-agent credentials and deploy nothing.
The separately maintained playground mentioned in the guides is not included in
this repository or package; see [example availability](integrations.md#example-availability).

## Guides and reference

- [72-hour playground experiment](playground-example.md): real Codex execution on a dummy storefront, an interrupted attempt, a completed repair cycle, and retained synthetic results.
- [Design and rendered charts](design.md): components, lifecycle, and recovery.
- [Class diagram and code structure](code-structure.md): current classes, modules, contracts and interactions across core and playground.
- [Four-stage orchestration](designs/four-stage-orchestration.md): implemented four-stage contract, rationale and remaining qualification.
- [Agent contract and skill template](designs/four-stage-agent-contract.md): the product knowledge and tools an integrating user supplies.
- [New user onboarding sequence](designs/new-user-onboarding.md): setup, rehearsal, first-cycle qualification and handoff with existing product capabilities.
- [Four-stage state chart](designs/aced-state-chart.md): rendered lifecycle, authority boundaries, execution, waits, stopping and recovery.
- [Product integration](integrations.md): what users configure and agents perform.
- [Runtime](runtime.md): embedding, scheduling, and control.
- [Local cycle manager](manager.md): offline demo, host adapters and UI boundaries.
- [Coding agent CLIs](agent-clis.md): Codex, Claude Code, Cursor and OpenCode routing and host setup.
- [Codex CLI](local-codex.md): Codex-specific sandbox and output-file configuration.
- [Qualification roadmap](roadmap.md): remaining live and operational work.
- [Asset sources](assets.md): demo screenshot and architecture diagrams.
- [Contributing](../CONTRIBUTING.md): checks and change discipline.

Older provider, vendor, and Framework guides were removed with the clean replacement.
Use the earlier package and its documentation for earlier preview databases.
