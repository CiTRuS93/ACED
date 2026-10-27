# Playground example: testing catalog ordering

**Recorded snapshot: October 24, 2026, 22:45 UTC.** A real Codex agent had reached
the main experiment in a synthetic storefront. The experiment was running at that
time; the snapshot does not establish product benefit, final disposition, or a
completed learning cycle. This page has no later readout.

The separately maintained playground supplies the shop, host integration, and
synthetic browser traffic. It is not included in this repository. This example
describes observed integration progress; the included [offline manager demo](manager.md)
is a separate deterministic fixture with its own synthetic data.

## The hypothesis and change

The goal is to improve eligible-session conversion while keeping checkout
reliable. The agent proposed showing in-stock catalog cards before sold-out cards,
while preserving the existing purchase forms.

The checked candidate, `db5ff5e0516bcc6883ab122846630604d95c8a12`, changes
`shop/storefront.html` and `feature_test.py` in the companion product. It reorders
existing catalog nodes. Checkout, pricing, and instrumentation are outside the
change. The host retained passing feature and template-contract checks, with
10 tests passing, before exposure began.

## What the records show

All times below are UTC on October 24, 2026, unless another date is shown.

| Step | Recorded observation |
| --- | --- |
| Implementation | Codex execution receipts record completed implementation and experiment tasks; host checks bind to the candidate source. |
| Canary | 10% treatment allocation from 04:56:38 to its planned 05:26:38 deadline; native records contain 304 control and 44 treatment browser sessions. The host recorded a passing canary verdict. |
| Canary closure | The native deadline-stop receipt records treatment allocation zero at 05:26:39.153628. |
| Main experiment | A separate experiment starts at 05:27:41.057222 with 50/50 allocation and explicit exclusion of the canary experiment. |
| Planned readout | The frozen main deadline is October 27 at 05:27:41.057222, followed by a 30-minute data-maturity delay. Actual zero exposure and mature evidence remain prerequisites for readout. |
| Snapshot status | At the October 24 snapshot, the run was active in cycle 2, at the Experiment stage; the native main-experiment record was running. |

These are real agent executions against a served test product with synthetic
browser sessions. They do not represent customer traffic or evidence of improved
conversion. The canary verdict concerns operational checks, not product benefit.

## Why this is cycle 2

The first attempt was interrupted before its fixed experiment horizon. Retained
learning records an operational error during safety observation, unknown business
effects, and rollback. Stop evidence also records operator involvement.

The second cycle is a repair attempt under the same hypothesis and plan. This
illustrates a useful distinction: recording an unsuccessful attempt and preserving
its uncertainty is progress in the development process, even when the experiment
cannot support a benefit decision. The records do not establish the operational
fault's root cause or fully autonomous recovery.

## Evidence and remaining work

This summary was checked against the companion runtime's retained task and learning
records, runner completion receipts, host check records, the candidate Git diff,
and the native product's experiment, allocation, and stop records. Local databases,
credentials, and raw execution records are not distributed with this documentation.
It is a dated summary, not a live status page or a publicly reproducible evidence bundle.

The completed readout, disposition, retained source, and subsequent learning were
not verified for this snapshot. Live integration progress does not qualify production credentials,
real-user exposure, supervised persistent operation, or unattended operation.
See the [qualification roadmap](roadmap.md) for the remaining requirements and the
[integration guide](integrations.md#example-availability) for the playground boundary.
