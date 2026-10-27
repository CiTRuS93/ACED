# Four-stage agent contract and product-skill template

Status: implemented development-preview contract; actual runner/product permissions and live-cycle qualification remain separate. Companion to the [four-stage design](four-stage-orchestration.md). These instructions do not authorize operating the live playground. These instructions are vendor-neutral. A host may package them in its chosen agent's skill mechanism; ACED does not require a new skill registry or vendor SDK.

## What ACED supplies for each invocation

Supply task/run/cycle/stage IDs, the exact current authority, goal/constraints, remaining budgets, accepted baseline, hypothesis/plan/candidate as applicable, previous accepted handoff, compact checkpoint, evidence/operation references and the writable evidence directory. Include the frozen instruction content/version and tool profile. Never place credentials in persisted task input.

The generic instruction is:

> Own the procedure for the assigned stage using the supplied product tools. Inspect actual state before consequential actions, especially after interruption. Work within the granted scope and budget. Investigate ordinary problems yourself; retain uncertainty when the available evidence cannot establish an outcome. Return a durable checkpoint when waiting on time, external work, approval or the next authority boundary. End this invocation when yielding. Report references to actual records so the coordinator can verify handoffs.

## Product skill: fields the integrating user fills in

| Field | Required product knowledge |
| --- | --- |
| Source | Repository, permitted product paths, accepted-source/artifact identity command, Git workflow and forbidden/private surfaces |
| Checks | Existing trusted test/CI commands, required project check definitions, where exact candidate-bound results are retained |
| Delivery | Existing deploy-disabled/restart/readiness/source inspection tools; how to observe a prior operation; rollback procedure and authority |
| Experiment | Existing canary/main controls, frozen-plan/operation keys, native status/closure/analysis records, population separation and allocation limits |
| Observability/diagnosis | Error, health, latency and feature signals; candidate/deployment/experiment queries; normal/failure test evidence; missing/stale-data policy; monitoring instructions and escalation owner |
| Research retention | Existing tracker or versioned artifact, stable candidate/initiative/phase IDs, dependencies, continuation criteria and links to prior outcome/learning |
| Disposition | Promotion/reversal tools and approval path, actual retained-source records, post-promotion observation requirements |
| Evidence | Writable artifact directory, stable reference format and retention; never use validated product source as scratch evidence storage |
| Authority | Actual tool permissions; boundary approval policy, authenticated approvers, existing approval channel, notification preferences and no-response/escalation behavior |

Prefer references to existing product documentation and real commands. Do not invent a command wrapper when an existing tool already provides the needed scope and records. Test these instructions with the actual runner; a successful login or two read-only commands does not qualify deployment, evidence writing or recovery.

## Stage-specific expectations

**Hypothesize:** investigate the goal using accessible evidence and prior learning. Preserve values/denominators, dates, cohorts and source references beside consequential claims. Explain the predicted mechanism, assumptions, alternatives and disconfirming evidence. Retain multiple candidates with stable IDs, claims, evidence, assumptions, expected value/learning, effort/risk, dependencies, selection/defer/rejection rationale and outcome links in an existing tracker or versioned artifact. Re-evaluate retained and external proposals against accepted source and learning. Explain priority relative to user priorities and effort; select one candidate and propose a complete cycle plan within the frozen host bounds, or reference the exact fixed plan when that policy is configured. Obtain host authorization for that concrete proposal before Implement. For linked phases retain parent initiative, phase/dependencies and continuation criteria. Earlier findings can change later phases. Several engineering increments can fit Implement; separate experiments require separate complete cycles. Preparatory engineering is not experiment success. Do not treat private simulator knowledge or unverified summaries as observed product evidence.

**Implement:** inspect the accepted baseline and current state, make the smallest change that tests the hypothesis, run the configured checks and fix ordinary failures. Return exact candidate/artifact and trusted check references, plus an observability handoff: signal/query references, verified normal/failure paths in the authorized test environment, monitoring instructions, missing/stale-data interpretation and the frozen guardrails. Reuse useful instrumentation and add missing error, health, latency or feature signals. Raw telemetry remains in native systems. If source changes after checks, rerun affected required checks. A failing test is normally work to investigate within this stage, not a request for a new orchestration stage. Do not deploy unless the current scope explicitly allows it.

**Experiment:** use the frozen candidate/plan and supplied scope. Under preparation/canary authority, deploy disabled, verify actual serving identity, readiness and usable telemetry before exposure, establish independent stopping and operate/review the bounded canary. Yield at canary closure; only a subsequent main-authorized invocation may start main. Retain its native identity and first-allocation receipt, then yield during long waiting. On resumption, inspect that experiment rather than create another one. Obtain the closed-window analysis after maturity. Explain failures and invalid/missing evidence without relabelling them as normal completion. No errors with absent traffic or telemetry is not health. The deterministic host monitor handles frequent safety checks and hard stopping; health does not establish business benefit.

**Decide:** interpret the exact readout or unsuccessful attempt, separate observed facts from causal explanations, and propose an allowed disposition and next action. If a new product effect is required, yield for disposition authority; after authorization, perform and observe it, including required promotion observation or rollback. Otherwise verify the already-settled retained source and return learning and the proposed continuation directly. Update retained candidate/phase outcome links, explaining whether later phases remain justified. Return retained-source evidence, learning, a goal assessment (`attained`, `not_attained` or `undetermined`) and one of `next_hypothesis`, `repair` or `finish`. A winning experiment need not attain the overall goal; an inconclusive result can still produce useful learning. Do not reopen a closed window or modify its frozen rule.

## Concrete retained handoffs

The evidence reader maps native records into the core guards. Agent output proposes these facts; it cannot certify them itself. Plan-authorization fields come from the host's approval of the exact research selection and plan, separately from permission to perform research.

| Handoff | Current required fields |
| --- | --- |
| Research | `hypothesis`, complete `plan` or configured fixed template, matching `plan_fingerprint`, host-verified `plan_authorized`, `plan_authorization_reference` and `plan_authorization_fingerprint`, `selected_candidate_id`, `research_reference`, `candidates`; optional `initiative` |
| Candidate | `id`, `claim`, `evidence`, `assumptions`, `expected_learning`, `effort`, `risk`, `dependencies`, `status`, `rationale`, retained `outcomes` |
| Linked initiative | `id`, `phase_id`, `dependencies`, `continuation_criteria` |
| Implementation | Exact `source_baseline`, `candidate`, `artifact`, accepted `plan_fingerprint`, project-defined `checks`, and `observability` |
| Observability | `reference`, `queries`, `normal_verified`, `failure_verified`, `monitoring_instructions`, `missing_data_policy`, matching `guardrails` |

Scope and instructions are frozen in `AgentTask`; neither a changed shared prompt file nor an approval for another candidate changes the running task. Run authority/budgets are fixed; the accepted complete plan is immutable for its cycle and any repair. A changed hypothesis or material plan change returns to Hypothesize and obtains fresh exact-proposal authority within the run bounds. Only one shared-resource owner may mutate or expose the product through cleanup.

A next-goal task can receive verified `continuity` identifying the prior terminal run, accepted source and selected learning/candidate records. Use those records and their retained references; do not assume an empty conversation means there was no earlier learning. A stopped-run `learning_unavailable` reason is an explicit gap, not successful evidence.

## Waiting, correction and interruption

- Use stable native operation keys. If an action response is lost, observe the original operation. Do not repeat it just because a process or HTTP request timed out.
- Separate an active, identified experiment under independent protection from an unknown action outcome. Report the latter as unresolved.
- Request a useful wake time or identify the pending native record/authority boundary. Do not keep a process sleeping for hours or poll unchanged health through repeated model turns.
- A checkpoint is a recovery aid. On resume, compare it with current native records; the records determine what happened.
- A correction task includes the prior immutable result and actionable feedback. Correct the report/evidence within the supplied scope; it does not automatically authorize repeating implementation, deployment or exposure.
- A reconciliation task identifies the original task/fingerprint and unresolved operations. Inspect and perform only authorized cleanup. Preserve the distinction between terminal execution, stopped exposure and completed rollback.
- Request host/library maintenance when required and outside scope. Product access alone does not authorize changing its monitor, verifier, runner records or permission configuration.

## Example result envelope

This illustrative result is a proposed checkpoint from an Experiment invocation whose main allocation is known and active. It is not authoritative proof of activation. The host reader must resolve the referenced native receipt; ACED derives the actual end from that record. The example references and timestamps are placeholders.

```json
{
  "outcome": "waiting",
  "summary": "Main allocation is active according to the referenced receipt; the independent monitor is armed.",
  "deliverable": {},
  "evidence": ["product://experiments/example-main/activation"],
  "operations": ["product://operations/example-start-main"],
  "checkpoint": {
    "notes": "Resume by observing example-main; do not create another experiment.",
    "accepted_source": "source://baseline-example",
    "candidate": "source://candidate-example",
    "experiment": "product://experiments/example-main"
  },
  "wait": {
    "reason": "native_record",
    "reference": "product://experiments/example-main",
    "not_before": "2026-10-20T10:30:00Z"
  },
  "blocker": null
}
```

Other envelope rules:

- `completed` supplies the current stage's deliverable; it cannot skip the next authority boundary or choose arbitrary stages.
- `waiting` names a native record, a useful timer or one of the current stage's permitted authority boundaries. A boundary request proposes no new privileges by itself.
- `blocked` names the specific missing access, approval, information or unresolved effect and the responsible owner. Do not use a generic “needs intervention” message when a concrete failure is known.
- `failed` retains the reason/evidence and a proposed disposition. It is not a retry permit and does not imply product exposure stopped.
- All four outcomes may include known outstanding operations. No empty list or omitted reference certifies that effects are settled; the host checks the invocation's actual scope and native records.

For the canary-to-main authority handoff, the same envelope contains a request like:

```json
{
  "outcome": "waiting",
  "summary": "The canary is closed; review its native window and zero receipts before allowing main exposure.",
  "deliverable": {},
  "evidence": ["product://canaries/example-canary/closed-window", "product://operations/example-canary-zero"],
  "operations": ["product://operations/example-canary-zero"],
  "checkpoint": {"canary": "product://canaries/example-canary"},
  "wait": {"reason": "authority_boundary", "boundary": "main_exposure"},
  "blocker": null
}
```

This ends the invocation. Core verifies its terminal execution and the native canary/zero evidence before preparing a new main-scoped invocation. Changing the boundary string grants nothing. A failed canary returns unsuccessful-attempt evidence; it does not request main authority. If no main experiment existed, preserve that fact rather than inventing a main readout.

ACED validates this small envelope and the consequential handoff facts. It does not grade every intermediate sentence or create a separate task merely to restate successful checks.

## Minimal integration rehearsal

Use a disposable product/profile. Demonstrate approved source/data reads, a trusted check, evidence writing outside the product, actual native status, a permitted control action and denied out-of-scope action. Then interrupt an invocation and recover from its checkpoint in a fresh session. Only after those work should the design's short full-cycle tests run. Keep all native receipts and record any manual repair explicitly.
