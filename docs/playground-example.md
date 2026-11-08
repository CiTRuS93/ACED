---
title: A 72-hour synthetic storefront product experiment with Codex
description: A development integration case study of a Codex agent running a 72-hour product experiment with synthetic storefront traffic. Not an agent benchmark or customer evidence.
---

# A coding agent runs a 72-hour product experiment in a synthetic storefront

A real Codex agent proposed, implemented, and tested an availability-first catalog
in the separately maintained `cddai-playground` shop. After an interrupted first
attempt, a second cycle completed its 72-hour experiment, waited for mature
outcomes, promoted the measured candidate, and retained the result and source.

**Records reviewed November 5, 2026; run completed October 27, 2026.** The synthetic
experiment met its configured conversion and checkout-error decision rule. This
is a development integration case study, not customer evidence or production
qualification. It updates the earlier October 24 snapshot, which correctly
reported that the main experiment was still running and no final result was known.

The playground supplies the served shop, host integration, and synthetic browser
traffic. It is not included in this repository. To explore the lifecycle locally,
start with the included [offline manager demo](manager.md) or
[offline Python example](runtime.md#run-an-offline-example). Those deterministic
fixtures are separate from this recorded experiment.

## The product hypothesis and checked change

The goal was to improve eligible-session conversion while keeping checkout
reliable. The agent observed unavailable products among the displayed catalog
cards and proposed showing in-stock cards first, preserving all cards and the
native purchase forms. Whether that would help was a hypothesis to test.

The second cycle's checked candidate,
`db5ff5e0516bcc6883ab122846630604d95c8a12`, changes only
`shop/storefront.html` and `feature_test.py` in the companion product. It reorders
existing catalog nodes; checkout, pricing, assignment, and instrumentation are
outside the change. The host retained passing feature and template-contract
checks, including 10 tests, before exposure. The registered storefront artifact is
`098847a1f9e83af9bcfddab536149e29fb000f7b32bd5bead19af971c756e570`.

The host bound checks, deployment, experiment, and disposition to that source and
artifact. Agents worked through task-scoped product tools; this local run used
preauthorized gates. It does not demonstrate a person approving each boundary.

## Canary, zero, then the separate main experiment

All times below are UTC in 2026. Times distinguish native deadlines from receipts
confirming actual zero experiment allocation.

| Step | Recorded observation |
| --- | --- |
| Checked implementation | October 24, 04:54:23: the host registered the checked candidate and artifact. |
| Operational canary | October 24, 04:56:38.895304: 10% treatment allocation began with a fixed 30-minute deadline. Native records contain 304 control and 44 treatment browser sessions; the host recorded a passing canary verdict. |
| Canary zero | The deadline was October 24, 05:26:38.895304. The native stop receipt confirms zero at 05:26:39.153628. |
| Main experiment | October 24, 05:27:41.057222: a separate experiment began at a fixed 50/50 allocation for 72 hours. It explicitly excluded the canary experiment; retained assignment records contain no shared shoppers between these two cohorts. |
| Main zero | The original deadline was October 27, 05:27:41.057222. The native stop receipt confirms zero at 05:27:41.409328. |
| Mature readout | The planned outcome cutoff was October 27, 05:57:41.057222, 30 minutes after the experiment ended. The host retained its mature analysis at 05:57:54.419890. |
| Disposition | A separately authorized disposition task promoted the exact measured release at October 27, 06:01:27.099279. |
| Retained learning | At October 27, 06:04:14.836767, the coordinator recorded `completed`, accepted the candidate source, retained the learning, and selected `finish`. |

The canary verdict concerns operational checks. The separate main experiment
supplies the product-benefit result. Agent invocations yielded during exposure;
the runtime retained the experiment identity and deadline through the wait.
An agent did not need to keep a conversation running for three days.

Zero here means the experimental allocation closed before readout. The later
promotion made the candidate the shop's accepted release; it does not mean the
promoted storefront stopped being served.

## What the synthetic A/B test measured

The frozen `shop-fixed-horizon-v1` rule counts paid orders per eligible browser
session enrolled during the main experiment, accepting outcomes through its
30-minute maturity cutoff. These are observed synthetic browser sessions, not
real shoppers or payments.

| Main-experiment observation | Control | Treatment |
| --- | ---: | ---: |
| Eligible browser sessions | 23,498 | 24,104 |
| Distinct synthetic shoppers | 4,791 | 4,800 |
| Paid orders | 1,246 | 7,292 |
| Conversion | 5.30% | 30.25% |
| Sessions with a checkout error | 13,067 | 7,089 |
| Checkout-error rate | 55.61% | 29.41% |

The retained analysis reports a **24.95 percentage-point conversion increase**,
with an approximate 95% interval of **23.82 to 26.05 percentage points**. The
checkout-error difference is **−26.20 percentage points**, with an interval of
**−27.46 to −25.03 percentage points**. These are differences in percentage points,
not relative percentage changes.

The host uses 2,000 bootstrap draws, resampling whole shoppers to preserve repeated
sessions within each shopper. The configured rule requires a positive lower
conversion bound and an upper checkout-error increase bound no greater than one
percentage point. This result met both conditions and returned `promote`.
Read-only recomputation from the native records matched the retained analysis.

The result describes this synthetic setup. Its large effect is not a forecast for
another storefront, and the remaining treatment checkout-error rate is not a claim
of universal checkout reliability. The approximate intervals assume independent
shoppers and intact assignment. Native data lacks a historical ingestion timestamp
that could exclude later backdated writes, so the host retains the first mature
analysis rather than continually replacing it.

## Why this is cycle 2

The first main experiment began October 22 and was interrupted on October 24,
before its planned 72-hour horizon. Retained learning records a safety-observation
`OperationalError`, unknown business effects, and rollback. The earlier October 24
snapshot also noted operator involvement. That attempt has no valid completed fixed-horizon
analysis: it is an unsuccessful operational attempt, not a statistically
inconclusive completed experiment.

The second cycle preserved the accepted hypothesis, fixed plan, and original
baseline, then performed a fresh implementation, checks, canary, and experiment.
Its successful completion establishes a completed retry. The retained evidence
does not establish the earlier fault's root cause, a specific verified repair, or
fully autonomous recovery.

The coordinator retained both outcomes. Cycle 1 keeps its uncertainty and baseline
source; cycle 2 retains the measured candidate and its evidence-linked learning.
The final `attained` assessment is scoped to completing one measured cycle under
the configured conversion and checkout-error requirements. The run finished;
these records do not demonstrate a later cycle consuming the promoted source.

## Evidence boundary and remaining qualification

This review cross-checked the companion runtime's task and learning records,
runner completion receipts, host check and readout records, candidate Git diff,
and native experiment, allocation, assignment, stop, and promotion records.
The record identities below distinguish this experiment from the offline demos:

| Retained identity | Value |
| --- | --- |
| Run | `f2a22d61-4369-4732-9cc8-b05bd119f8e4` |
| Canary | `f2a22d61-4369-4732-9cc8-b05bd119f8e4:2:canary` |
| Main experiment | `f2a22d61-4369-4732-9cc8-b05bd119f8e4:2:experiment` |
| Frozen plan fingerprint, both cycles | `bfc480fb6b31ae4b83754ff39dc4dd71cd87a33aa3810f6dd77691345e863481` |
| Original accepted source | `525e428805d9095f86ec1229e73ba6d33d5221ff` |
| Final accepted source | `db5ff5e0516bcc6883ab122846630604d95c8a12` |

Payment duplication and inventory violations remain unknown in the retained
analysis. The planned checkout-error check includes the 30-minute outcome delay;
broader delayed harm was not verified. The frozen plan had no additional
post-promotion observation window. Local execution used a trusted account and
did not establish filesystem isolation or a blinded evaluation.

Local databases, credentials, private simulator internals, and raw execution
records are not distributed with this documentation. This is a dated, sanitized
summary, not a live status page or a publicly reproducible evidence bundle.
A completed synthetic integration cycle does not qualify production credentials,
real-user exposure, supervised persistent operation, or unattended operation.
See the [qualification roadmap](roadmap.md) for remaining requirements and the
[integration guide](integrations.md#example-availability) for the playground boundary.
