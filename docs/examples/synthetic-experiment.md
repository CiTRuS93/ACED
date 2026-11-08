# Run a synthetic product experiment with coding-agent tasks

See the complete development loop in seconds: research, implementation, canary,
separate main experiment, decision, and a second cycle that receives the previous
source and learning. Every agent and product record in this example is a
deterministic fixture, so it needs no agent account or served product.

From a source checkout with Python 3.12+, install the core and run:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/synthetic_experiment.py
```

Expected output:

```text
Cycle 1: hypothesize / research
Cycle 1: implement / implementation
Cycle 1: experiment / preparation_canary
Cycle 1: experiment / main_exposure
Cycle 1: decide / decision
Cycle 1: decide / disposition
Cycle 2: hypothesize / research
Cycle 2: implement / implementation
Cycle 2: experiment / preparation_canary
Cycle 2: experiment / main_exposure
Cycle 2: decide / decision
Cycle 2: decide / disposition
Completed: 2 cycles; 12 fixture tasks; 2 retained learning records
Each canary reached zero before its separate main experiment
Cycle 2 received source-1 and prior learning; retained source: source-2
All fixture experiments closed; audit valid: True
```

The [complete script](../../examples/synthetic_experiment.py) composes `Runtime`
with the included reference project, simulated clock, fixture runner and synthetic
host evidence. It advances the loop at most 300 times and checks that both cycles
complete, each canary reaches zero before its separate main experiment begins,
and all fixture experiments close. It also checks the second research task's
accepted source and prior learning, plus the complete audit history. SQLite uses a
fresh temporary directory that is removed when the example exits.

The `source-1` and `source-2` labels and promotion outcomes are preset fixture
records. They are not commits, measured conversion improvements, real deployment
receipts or statistical analysis. `DemoIdentity` provides fixture authority, not
authentication. The script makes no network calls, launches no coding CLI, changes
no product and sends no traffic. The package remains a development preview without
production, real-user or unattended qualification.

For real agent execution against a dummy storefront and synthetic browser traffic,
read the dated [playground case study](../playground-example.md). That separately
maintained host is distinct from this portable fixture. The [runtime guide](../runtime.md)
explains embedding ACED; the [integration guide](../integrations.md) describes the
authoritative evidence and independent stopping that a host must supply.

## If your own experiment does not advance

This checklist applies after you have supplied and separately authorized a host
integration. The fixture above skips wall time with a simulated clock; a real host
must wait for its frozen exposure and maturity windows. Start with authenticated
`Runtime.inspect(run_id)`: note the current stage, scope, blocker and wake time.
Use `Runtime.tasks(run_id)` and `Runtime.history(run_id)` only with the required
evidence-read claims, then compare with the host's native records. Inspection may
redact the scope and blocker without those claims; `restricted evidence` means
the caller lacks access, not that the experiment itself has failed.

| What you observe | What to check next |
| --- | --- |
| The agent exited, but Experiment is still active | An invocation can end while native work continues. Verify the original task, execution, candidate/artifact, plan and experiment identities. Keep independent monitoring/stopping available; do not relaunch merely because the agent exited. |
| The canary passed, but main exposure has not begun | Confirm actual canary zero/end, minimum duration and samples, health/checks, and separate main cohort with canary exclusion. Inspect the new main task's authorization. A canary pass alone is not permission to expose the main cohort. |
| The main deadline passed, but Decide has not started | Distinguish closure from maturity. First verify native zero/end for the original fixed window; then wait for the frozen readout delay and a retained native readout with the matching rule, validity and outcome. Elapsed time alone proves neither closure nor evidence availability. |
| The result is inconclusive or does not favor the candidate | Keep the planned window and mature readout unless a safety trigger or authorized stop applies. A business result alone is not an operational emergency. Missing traffic or telemetry cannot establish healthy operation or justify promotion. |
| A stop was acknowledged, but the run remains stopping | Verify actual zero, native protection against late re-exposure, and settled execution/effects. A delivery acknowledgment is not closure. Use the [recovery checklist](resume-workflow.md#if-your-own-run-is-still-waiting) for unresolved effects. |
| The readout favors promotion, but the source is unchanged | Inspect Decide's proposal and disposition authority. Promotion needs the exact measured candidate, independent protection, rollback readiness and the configured observation. A readout recommendation does not itself deploy or authorize promotion. |

At normal expiry, closure observation may briefly wait. Continued canary/main
experimental exposure beyond the host's bounded closure grace requires stopping
even when health looks good. Later serving from a separately authorized promotion
has its own protection and observation requirements.
Real harm, sustained monitoring failure and identity mismatch retain their safety
causes. Do not extend a frozen deadline, relax the decision rule, invent zero, or
copy expected identities into observed facts to make a blocked handoff pass.
The [host contract](../integrations.md#host-interface) and
[handoff facts](../integrations.md#consequential-handoffs) define those checks;
ACED does not supply your product's statistics, instrumentation or stop executor.

## Keep the three kinds of evidence separate

- **This example:** a repeatable two-cycle fixture checks orchestration, canary/main
  separation and source/learning continuity. Its preset promotion is not a measured
  product result.
- **The recorded storefront cycle:** the [case study](../playground-example.md)
  describes actual Codex execution and a measured synthetic experiment. Its run
  finished after promotion; it does not show a later cycle consuming that source
  or prove autonomous recovery from its interrupted first attempt.
- **Your host:** retain private native records for the exact versions, identities,
  authorizations, deadlines, actual closure, readout, disposition and learning,
  including manual interventions and unresolved gaps. Apply the
  [qualification roadmap](../roadmap.md) before claiming a broader operating profile.

For a support report, share redacted versions, the stage/scope, expected transition
and observed blocker, following the [contribution guide](../../CONTRIBUTING.md).
Keep credentials, private prompts, runtime databases and raw product records out of
public issues. A passing audit or fixture cannot qualify real users, production
credentials or unattended operation.
