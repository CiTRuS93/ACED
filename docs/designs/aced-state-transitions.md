# State chart transition guards

Status: **implemented development-preview guards; live qualification pending**. Companion to the [rendered state chart](aced-state-chart.md). These IDs are documentation references, not event names or new public API values.

Every transition also inherits the common control, authorization, identity and persistence guards in the companion document. A stage change and an agent invocation are different operations.

## A · Run lifecycle

| ID | From → to | Event / full guard |
| --- | --- | --- |
| L1 | Accepted start → Hypothesize | **create run.** Accepted goal, constraints, budgets and source; verified identity and exclusive product ownership. |
| L2 | Hypothesize → Implement | **plan accepted.** Hypothesis, references, assumptions and full bounded plan accepted and frozen before exposure. |
| L3 | Implement → Experiment | **checks accepted.** Exact candidate, required trusted checks and normal/failure observability handoff accepted; implementation execution settled. |
| L4 | Experiment → Decide | **attempt settled.** Every actual operation settled; zero where exposure existed; mature analysis or verified unsuccessful/invalid outcome. |
| L5a | Hypothesize → Decide | **safely abandoned.** Account for execution/effects and retain abandonment reason; enter Decide with unsuccessful attempt. |
| L5b | Implement → Decide | **same guard.** No exposure or unaccounted effect can be silently discarded. |
| L6 | Decide → Hypothesize | **next_hypothesis · new cycle.** Accepted retained source, learning and assessment; settled disposition; remaining authority/cycle/invocation budget. |
| L7 | Decide → Implement | **repair · new cycle.** Same frozen hypothesis/plan; safely closed attempt; explicit repair authority and budget; fresh exposure identities and checks. |
| L8 | Decide → completed | **finish.** Accepted settled disposition, retained source, required observation, learning and assessment; atomic acceptance. |
| L9 | Stop / reconcile → stopped | **operator stop + settlement.** F6 guard: execution/effects/exposure and required disposition safely settled; retained source and factual outcome. |

## B · Inside Experiment

| ID | From → to | Event / full guard |
| --- | --- | --- |
| X1 | Preparation / canary → Canary boundary review | **boundary requested.** Old invocation returns a canary-boundary wait; request is not authority. |
| X2 | Canary boundary review → Main authority available | **main scope granted.** Exact candidate/deployment/plan/canary; duration/traffic/operational criteria, confirmed zero, population separation, prior execution terminal/fenced and current authority. |
| X3 | Main authority available → Main active / waiting | **activate once under protection.** Main-specific durable protection acknowledgment precedes allocation; activation binds native first start/end without an unprotected interval. |
| X4 | Main active / waiting → Closure pending | **native end / closure event.** Normal deadline causes closure observation, not automatic failure. Early zero/harm is an unsuccessful-attempt path. |
| X5 | Closure pending → Readout pending | **zero verified.** Actual exposure zero and operations settled; readout maturity may still be pending. |
| X6 | Readout pending → Decide | **valid mature analysis accepted.** Exact experiment/window/rule, maturity and validity; every actual operation settled. No model need run merely because time passes. |
| X7 | Unsuccessful attempt → Verify settlement | **check settlement.** For an established unsuccessful attempt, verify actual operations/exposure. Reconcile only if needed; never assume zero. |
| X8 | Verify settlement → Decide | **unsuccessful outcome settled.** Verify what existed and absence of nonexistent main exposure. No invented main/readout/zero receipt. No sticky operator stop. |
| X9 | Preparation / canary → Unsuccessful attempt | **established failure.** The failure path is available from every Experiment condition. Unknown activation alone is not a failure; first observe the original operation through D/E. |

## C · Inside Decide

| ID | From → to | Event / full guard |
| --- | --- | --- |
| D1 | Interpret / propose → Disposition boundary | **new effect required.** Proposal is evidence-backed and requests only the relevant disposition authority. |
| D2 | Disposition boundary → Authorized disposition | **scope granted.** Old execution terminal/fenced, action eligible and currently authorized. Promotion also requires independent delayed-harm protection and separately authorized rollback ready. |
| D3 | Authorized disposition → Observation / settlement | **perform + observe.** Use native tools; preserve actual effect/operation references; yield for long observation. |
| D4 | Observation / settlement → Accept decision | **settlement verified.** Required observation complete or reversal verified; retained source and every actual effect settled. |
| D5 | Interpret / propose → Accept decision | **no effect needed; already settled.** Verify retained source and actual settlement; no ceremonial disposition invocation. |
| D6 | Accept decision → Correction / blocker | **unusable / incomplete.** Bounded actionable correction or named blocker; not automatic retry, repair or another branch. |
| D7 | Correction / blocker → Interpret / propose | **resolved + authorized work.** New task only if needed, previous execution/effects settled and authority/control/budget permits. |
| D8 | Accept decision → Hypothesize | **next_hypothesis.** Atomic accepted source/learning/assessment/action; settled disposition; remaining budget and authority. |
| D9 | Accept decision → Implement | **repair.** Explicit repair authority and budget; preserve plan, create fresh canary/main identities and rerun checks. |
| D10 | Accept decision → completed | **finish.** Full normal-completion guard; learning is required. |

## D · Per-task execution

| ID | From → to | Event / full guard |
| --- | --- | --- |
| T1 | Prepared task → Authorization pending | **approval pending.** Approval waits are durable. Time alone never approves the request. |
| T2 | Authorization pending → Blocked | **denied / unavailable.** Keep owner, reason and external decision reference; no automatic terminal or new stage. |
| T3 | Prepared task → Launch eligible | **authorization allowed.** Existing host authorization binds the immutable task and actual tool scope; recheck current eligibility before dispatch. |
| T4 | Authorization pending → Launch eligible | **actual approval.** Observe a changed decision; no re-reservation or execution charge for waiting. |
| T5 | Launch eligible → Original execution | **dispatch once.** Ordinary work requires not held/stopping and sufficient reserved budget; reconciliation uses its own allowed scope. Expanded scope also requires prior settlement and accepted facts. |
| T6 | Original execution → Execution unknown | **lost response / crash.** Launch or running-state uncertainty: observe the same task/execution, never blindly start replacement. |
| T7 | Execution unknown → Original execution | **running confirmed.** Recover original identity; same execution, same budget charge. |
| T8 | Original execution → Execution settled | **terminal proof.** Process completion alone does not settle product effects. Output may be absent or invalid. |
| T9 | Execution unknown → Cancel requested | **deadline / stop.** Cancellation may be requested without claiming it succeeded; independent exposure stop does not wait here. |
| T10 | Cancel requested → Execution settled | **terminal / fenced.** Native evidence establishes execution cannot continue; still reconcile external effects. |
| T11 | Execution settled → Result disposition | **process result.** Original result saved once, or retain explicit error/no-output diagnostic; use E. |

## E · Result, evidence and durable waiting

| ID | From → to | Event / full guard |
| --- | --- | --- |
| R1 | Retained result / error → Inspect / verify | **retain once + inspect.** Store original content once. Agent outcome is separate from process status. |
| R2 | Inspect / verify → Accepted facts / handoff | **facts accepted.** Exact identities, current authorization and required boundary/settlement guards. A completed claim alone is insufficient. |
| R3 | Inspect / verify → Durable wait | **named pending dependency.** A valid waiting result or genuinely pending evidence/approval; record wake/dependency and last change. |
| R4 | Inspect / verify → Correction required | **usable correction path.** Bounded correction with actionable feedback, preserved original result and remaining authority/budget. |
| R5 | Inspect / verify → Named blocker | **blocked / exhausted.** Specific reason; denial, absent capability or unusable results at limit. No fabricated success or generic terminal failure. |
| R6 | Durable wait → Inspect / verify | **due native recheck.** Re-read native authority after wake hint. Accept available facts or prepare needed new work through D only after task/control/budget guards pass. |
| R7 | Correction required → New task if needed | **bounded new invocation.** Old execution terminal/fenced; effects accounted for. Each correction consumes invocation + correction budgets; mutation requires explicit scope. |
| R8 | Named blocker → Inspect / verify | **dependency actually changes.** Recheck authority/evidence; change alone is not permission to mutate or broaden scope. |
| R9 | Inspect / verify → Failure / uncertainty | **failed / unknown effects.** Failure can require F reconciliation; unknown execution first requires D observation/fencing before mutable cleanup. |
| R10 | Failure / uncertainty → Decide / safe outcome | **settled unsuccessful attempt.** Safe abandonment/operational failure may reach Decide. Sticky operator stop instead ends stopped through F. |
| R11 | Failure / uncertainty → Inspect / verify | **original outcome established.** Observe original operation/execution and recheck native facts. A correctly protected active experiment may continue its wait without zero, stopping, renewed deadline or duplicate activation. |

## F · Hold, stopping and reconciliation

| ID | From → to | Event / full guard |
| --- | --- | --- |
| F1 | Ordinary scheduling → Held | **hold.** Hold blocks ordinary new launches; already completed output/verified facts may advance recorded stage while hold remains. No implied suspension, revocation or zero. |
| F2 | Held → Ordinary scheduling | **resume + recheck.** Recheck authority/safety; never clears sticky stop or undoes reconciliation. Settled read-only Decide may resume with fresh native zero, explicitly absent exposure, independent stopping and no current effectful task despite a retained historical incident. |
| F3 | Stop / incident → Stop delivery | **stop required.** Any stage may enter. Persist operator intent only for operator stop; operational failure retains its own cause. |
| F4 | Stop delivery → Settlement pending | **send + observe.** Send before or alongside cancellation. Observe native stopping even if delivery is uncertain; retry unknown delivery with SAME identity. Acknowledgment is not zero or applied protection. |
| F5 | Settlement pending → Authorized reconciliation | **observe + reconcile.** Observe stop/execution in parallel. Cleanup task uses current stage and purpose=reconcile; cannot start another experiment. |
| F6 | Authorized reconciliation → Closure verified | **all closure facts verified.** Exposure zero where it existed, old execution terminal/fenced, no late re-exposure, every actual operation and required rollback/disposition settled, retained source known. |
| F7 | Authorized reconciliation → Reconciliation blocked | **cannot establish closure.** Unresolved evidence, denied cleanup authority or exhausted cleanup allowance stays nonterminal. Independent stopping continues. |
| F8 | Reconciliation blocked → Authorized reconciliation | **actual resolution.** New evidence/authority and bounded cleanup scope; no automatic retry or invented settlement. |
| F9 | Closure verified → stopped | **operator stop.** Sticky operator stop wins over all other continuation; retain factual outcome and learning or explicit learning_unavailable gap. |
| F10 | Closure verified → Decide | **operational failure.** No operator stop; hold remains. Settled failure can be accepted into Decide; any new decision/repair invocation still needs authority and budget. |


## Policy choices applying to every guard

Budget exhaustion, denied authority and correction exhaustion remain named nonterminal blockers. An authenticated dependency change can permit progress; explicit `stop` can request safe abandonment through reconciliation. There is no automatic successful finish or invented failure terminal. The separate finite cleanup allowance does not disable independent stop delivery. Invalid admission fails before persistence. Current approval and exact proposal identity must be rechecked at dispatch; elapsed time, notification acknowledgment and unrelated chat text are never authority. Later handoff acceptance rechecks current authority for the original authorized work without renewing launch permission, so a validly used approval expiring during a native experiment does not invalidate its mature readout.

Candidate changes invalidate checks, observability identity and unrelated approvals. Frozen run authority bounds admit a complete agent-proposed plan at Hypothesize after exact host authorization; fixed-plan policy is optional. The accepted cycle plan cannot change mid-cycle. A new hypothesis obtains a fresh plan admission; repair preserves its hypothesis/plan/baseline and requires fresh exposure identities and checks. One shared `resource_id` is owned through cleanup in the common store, including held and stopping states.

A new run's explicit `RunContinuation` must name a terminal settled predecessor, matching shared resource and accepted source, and existing selected learning/candidate records. Core authenticates access and retains lineage. Missing or unrelated references reject admission; an explicit stopped-run learning gap is retained as a gap.

After confirmed closure, fresh unexpected positive exposure re-enters stop/reconcile
with a new stop request even if reported healthy and identity-matched. Preserve the
old request and settlement history; invalidate cached closure until the new obligation
settles. A stale pre-closure report is not new exposure. Actual authorized promotion
observation is the only disposition exception, not an unlaunched proposal or rollback.
