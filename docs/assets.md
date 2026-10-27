# Documentation asset sources

Paths below are relative to the repository root.

## manager-offline-demo.png

Screenshot: `docs/images/manager-offline-demo.png`, captured October 27, 2026
(UTC) from the included offline manager fixture. The existing browser journey
used system Chromium against a disposable loopback server and checked approvals,
charts, scheduling controls, continuation, reconnect, stop, and mobile layout.

The screenshot shows a completed fixture cycle with zero exposure and an
inconclusive synthetic readout. It contains no live-agent result, customer data,
or evidence from the separate playground experiment. It is a browser capture,
not a generated illustration. Reproduce with the manager browser checks in
[CONTRIBUTING.md](../CONTRIBUTING.md#manager-development-checks).

## Architecture charts

The current design embeds `docs/images/four-stage-orchestration.png` and its
editable `.svg` source: four stages, agent-owned procedures and host-owned
identity, evidence and independent stopping. It describes the implemented preview;
actual runner/product qualification remains separate.

The onboarding guide uses `docs/images/new-user-onboarding.png` and `.svg` for the
complete sequence, with `-setup`, `-rehearsal`, `-cycle` and `-handoff` PNG/SVG views.
`new-user-onboarding-overview.png` and `.svg` provide the shorter overview. Adjacent
`.mmd` files retain editable sequence sources. These describe a separately
authorized integration/qualification procedure, not a completed live onboarding.

The complete state chart is `docs/images/aced-state-chart.png` and `.svg`. Six
readable views use the `aced-state-` prefix with `lifecycle`, `experiment`,
`decision`, `task`, `result` and `controls` suffixes. Each has PNG/SVG exports and an
adjacent `.mmd` source. Descriptive conditions are not extra public stage enums.
The companion documents specify resolved hold, denial and exhaustion policies.

These are committed deterministic diagrams; no Mermaid renderer is required.
The [class diagram and code structure](code-structure.md) uses seven
`docs/images/aced-class-*.svg`/`.png` views: overview, runtime, configuration,
contracts, host, product and support. SVGs are editable static sources; each PNG is
rendered from its SVG using librsvg/Cairo. Adjacent `.mmd` files retain class and
relationship definitions for alternate Mermaid layouts. These describe the current
working code, including classes, procedural modules and distinct storage surfaces;
they do not certify live qualification. The source inventory in the guide is
checked against Python class definitions without importing or executing packages.
