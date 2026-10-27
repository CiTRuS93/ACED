# Integrating a product

ACED owns four durable stages. Agents own research, implementation/test loops,
deployment/experiment procedures and decision/learning through existing tools. The
host owns identity, permissions, trusted records, statistics, process supervision and
independently available monitoring/stopping. No second lifecycle or general tool broker
belongs in the adapter.

## Example availability

Start with the included [offline manager demo](manager.md#offline-demonstration) or
the [complete Python example](runtime.md#run-an-offline-example) to explore the loop
without credentials or a product integration. Both use deterministic fixtures and
synthetic evidence; they do not qualify a live host.

References to **the playground** in this documentation describe a separately
maintained `cddai-playground` checkout, which retains its existing name. Its product,
host adapters, approval inbox, operator commands and host tests are not included in
this repository or package.
The descriptions below illustrate that host's contract; they are not an installation
path for a bundled integration. Commands such as `prepare`, `observe`, `work` and
`repropose-plan` belong to that separate host, not the `aced` CLI. You do not need
the playground to run the included offline examples.

To connect your own product, supply the inputs and interfaces below. The
[onboarding sequence](designs/new-user-onboarding.md) describes preparation and
qualification after those product capabilities exist.

## Six inputs a new user supplies

1. A measurable goal, constraints, accepted source, stable shared-product resource ID,
   plan template and optional `PlanBounds`, required check names and finite ordinary/correction/cleanup budgets.
2. A registered `AgentRunner`, tested execution profile and writable evidence directory
   outside validated product source; protected runner records and credentials.
3. Product instructions naming existing source/check/delivery/experiment/diagnostic tools,
   record locations, private surfaces, Git workflow and recovery procedures.
4. Authenticated identity and approval policy by scope, authorized approvers, existing
   approval channel, notification destinations/events, failure/no-response/escalation behavior.
5. A small reader translating authoritative source, checks, deployment, experiment,
   analysis, disposition and execution-settlement records into core facts.
6. Existing independent deterministic monitoring/stopping, worker supervision, durable
   storage/backups, and sufficient traffic for the selected experiment rule.

Typed Python composition is the supported core configuration. The standalone playground
may keep its existing goal backlog file; that is not a core configuration framework.
Missing assignment, observability, reversible controls or trusted records are product
prerequisites. A prompt cannot supply them.
An agent-accessible Git repository must also contain only public product history:
denying a private working-tree path does not hide its Git objects. The playground
requires a separate product-only main checkout and validates that boundary before
launch. Preparing that checkout does not switch a service or migrate any run.
The playground sets `require_research_observation=True`: prepare the held run,
capture its scoped observation, then resume and work. The host validates the snapshot
before recording it and before research dispatch. Later hypothesis cycles require a
new observation matching the new cycle and accepted source; missing evidence waits
before task inputs freeze. Completed tasks missing that input can receive a bounded,
authorized correction after execution, unchanged source and native zero are verified.

## Host interface

```python
class Infrastructure:
    async def authorize(self, task, principal, *, purpose="dispatch"): ...
    async def read_evidence(self, request, principal): ...
    async def safety(self, project_id, run_id, principal): ...
    async def request_stop(self, request, principal): ...
```

`authorize` returns `Authorization(status, task_fingerprint, reference, valid_until,
reason)`. Allowed, waiting and denied are durable observations. Authorize only the
concrete immutable task, scope and profile, rechecking current prerequisites. It must
not run checks, deploy, arm controls or perform another procedural stage.
`purpose="handoff"` rechecks current authority to accept evidence from the original
execution. This cannot grant new effects or renew launch authority. Expiry of an already
used launch approval does not invalidate a later native readout; policy denial or
approver revocation still blocks acceptance. A host must distinguish these purposes
so a long experiment can close after its agent invocation and launch approval expire.

`EvidenceRequest` includes `task`, optional `result`, `expected` identities, `purpose`
(handoff or settlement), and the current `boundary`. `read_evidence` returns
`Verification(status, task_fingerprint, facts, evidence, observed_at, valid_until,
reason)`. Reauthorize resource access, read native identities, compare them with the
request and return redacted diagnostics. **Never copy expected identities into observed
facts as proof.** An agent's result and list of operations are claims to reconcile.
`Evidence` carries a retained reference/digest and optional read claims. Large telemetry
and logs remain in existing host systems.

`SafetyStatus` distinguishes health, independent-stop readiness, zero, native exposure
end/identity, degraded monitoring and its original `last_success_at`, explicit stop
requirement/reason and applied protection. A report expiring at the known normal end
causes closure observation, not automatic failed-experiment classification. Continued
missing closure beyond bounded grace requires stopping/reconciliation. Real harm,
sustained monitoring failure and identity mismatch retain their causes. No telemetry
or traffic cannot establish healthy operation.

Configure operational safety thresholds, observation windows, minimum traffic and
missing-data rules in the host before exposure; retain their references in the
frozen plan's guardrails. The host evaluates these triggers deterministically and
keeps its independent stop executor available throughout canary and main exposure.
An ambiguous or nonwinning business result alone must not set `healthy=False` or
`stop_required=True`: business outcomes belong in the native readout and Decide.
A predefined safety trigger still takes precedence over business results. Normal
expiry closes exposure as planned; positive exposure beyond its bounded closure
grace requires a stop even if health remains good. Actual authorized promotion
uses its separate observation and protection obligations.

Fresh positive exposure after confirmed zero requires a new stop even if reported
healthy with matching candidate/plan/experiment identities. The earlier settlement
remains evidence, not permission to ignore the new report. Only an actual authorized
promotion invocation permits expected positive serving during disposition observation;
readout waits, a disposition proposal and rollback authority do not.

`request_stop(StopRequest, principal)` delivers one durable idempotent identity to the
existing independent executor. `StopDelivery.accepted` only acknowledges delivery.
Observe actual zero and the native latch/fence separately. Apply stopping before or
alongside cancellation; a late action from the old invocation must be unable to re-expose.
Cleanup authority and emergency rollback must remain available during ordinary approval
waits. The hook is a narrow safety operation, not a command-execution framework.

## Consequential handoffs

The exact predicates live in [workflow.py](../src/aced/workflow.py). The following
names are the actual `Verification.facts` contract. `execution_settled` and
`effects_settled` are required for handoff; active identified protected native work
can yield a wait without claiming closure.

| Boundary | Required facts |
| --- | --- |
| Hypothesize | `hypothesis`, complete `plan` or fixed template, exact `plan_fingerprint`, `plan_authorized`, `plan_authorization_reference`, `plan_authorization_fingerprint`, `selected_candidate_id`, retained `research_reference`, structured `candidates`; optional linked `initiative` |
| Implement | `source_baseline`, exact `candidate`/`artifact`, passed product-specific `checks`, required `observability` handoff |
| Preparation/canary | Candidate/artifact/deployment/plan and canary identity, cohort/allocation, native `started_at`/`deadline`, `serving_candidate`, `ready_before_exposure`, `telemetry_verified`, `deadline_stop_armed`; passed canary also requires actual zero/end, health/checks/minimum samples/duration and `canary_excluded` |
| Main exposure | Same exact identities and original fixed deadline, separate cohort, `canary_excluded`; active returns durable wait. Closed requires actual zero/end at deadline, maturity, native rule/validity/outcome and `readout_reference` |
| Unsuccessful attempt | `unsuccessful`, reason, verified actual closure/settlement and `main_started`; actual window if main existed. Absence of main must be verified, with no fabricated receipt |
| Disposition proposal | Exact candidate/baseline/plan, zero, eligible `proposed_disposition`, immutable `proposal_reference`; promotion also needs ready independent protection and rollback authority |
| Decide completion | Actual `disposition`, `accepted_source`, required promotion observation or rollback, `learning`/`learning_reference`, `goal_assessment`/`assessment_reason`, `next_action` finish/next_hypothesis/repair; repair also requires explicit `repair_authorized` |
| Reconciliation | Exact original task/fingerprint bindings in `settled_tasks`, zero, execution/effect settlement, `stop_request_id`, `stop_protection_applied`, matching native identities and accepted source, required rollback; learning or explicit stopped-run gap |

Research candidates retain stable IDs, claims, evidence, assumptions, expected learning,
effort, risk, dependencies, selected/deferred/rejected status, rationale and linked
outcomes. The agent prioritizes; core does not impose a scoring formula. A retained
tracker/versioned artifact is the durable source, not conversation history. Linked
phases carry parent initiative, phase ID, dependencies and continuation criteria.
Engineering increments can stay in Implement; each real experiment gets its own cycle.
Later findings may revise or cancel phases. Background proposal discovery is an explicit
future extension through existing bounded scheduled research, not concurrent scheduling
provided by this sequential runtime.

Hypothesize can select a complete plan within the run's frozen host bounds. The host
authorizes the exact returned plan and selection separately from permission to perform
research. Without bounds, only the template is admissible. Repair preserves the accepted
plan; a later hypothesis requires new admission. For a new run on the same product,
`RunContinuation` selects up to 32 retained learning references and candidate IDs from
a settled prior run. The host verifies the actual accepted checkout before starting;
core binds the prior revision/digest, resource, source and evidence read authority.

`observability` requires a retained reference, queries, monitoring instructions,
missing-data policy, verified normal/failure paths and the frozen guardrail references.
Implement verifies signals in its test environment. Experiment verifies actual serving
identity/readiness/telemetry after disabled deployment and before canary. Business
benefit remains distinct from operational health.

The playground requires a candidate-committed observability manifest approved for the
exact implementation task. It names instrumentation, queries, missing-data instructions,
normal/failure checks and the accepted guardrails. The host combines those checks with
its frozen baseline suite and records an immutable per-invocation receipt. Frozen
baseline tests run in a separate pytest process with host configuration and no
candidate conftest/hooks; feature probes run separately with their candidate fixtures.
The host retains the baseline report before running probes, binds both report digests
and return codes, and requires both to pass. `check_runs.baseline` and
`check_runs.probes` retain those records; `observability.baseline_test_report` names
the baseline report and `observability.test_report` names the probes. Repair uses
a fresh task and check invocation even when candidate bytes are unchanged. Two scoped
helper operations, checks and protection arming, run in the existing host worker;
the agent submits requests without receiving private runner records or host credentials.
When checks need human review, the agent returns the exact retained request and eventual
receipt references, then exits. The host observes that original request and can accept
the saved output after the approved checks finish. An unanswered request remains waiting;
expired dispatch authority cannot be renewed by accepting an old result.
Trusted candidate tests use a private network namespace for local HTTP tests, with no
route to the host network or external services. This requires Linux bubblewrap and the
installed Codex filesystem sandbox; missing isolation fails closed.
Replaying a retained protection-arming request observes its original native operation
and repairs derived publication/receipt records before considering new dispatch.
Original outcome observation remains available after expiry or revocation, but absent
native effects still require current authority. The private original proposal fixes
the activation window; replay never extends it or overwrites a newer watchdog target.

## Agent and approval contracts

Each `AgentTask` freezes purpose (`work` or `reconcile`), scope, predecessor, instructions,
runner, tool profile, source/plan/context, execution deadline and spending envelope.
`instruction_digest` identifies its retained content. The only development stages are
four; `preparation_canary`, `main_exposure`, `decision`, `disposition`, `correction` and
`reconcile` are restricted authority scopes. An old invocation ends or is fenced before
expanded scope is prepared.

The result envelope has `outcome` completed/waiting/blocked/failed, summary, deliverable,
evidence, operations, checkpoint, wait and blocker. See the
[agent contract/template](designs/four-stage-agent-contract.md). Waiting identifies a
timer, native record or allowed authority boundary and ends the invocation. A correction
gets the original immutable result reference and actionable feedback; settled effects
and host `correction_safe` are required. It does not grant deployment or exposure scope.
The runner uses stable `ExecutionRef(task.id, task.id)` after a lost launch response.
Built-in [CLI runners](agent-clis.md) cover Codex, Claude Code, Cursor and OpenCode;
their native permission modes require separately prepared and qualified host profiles.

Approval requests must retain an identity, exact task fingerprint, scope and concrete
proposal. Authenticate approver responses, match request/fingerprint/scope, check current
policy/expiry and recheck prerequisites. Delivery acknowledgment and arbitrary chat text
are not authorization. A changed candidate, plan or proposal needs new approval.

The current playground implements a minimal local approval inbox and authenticated
operator `approvals`/`approve`/`deny` commands under its protected state directory. The
local OS identity must match the configured approver; no messaging service is required.
Its host guide documents policy and command syntax. Other systems can reuse their
existing connection in `authorize`; a delivery failure or no response remains waiting
or escalated according to configuration. The playground consumes event preferences
into a protected local event inbox and rejects unsupported destinations. The timing
policy escalates unanswered proposals without treating elapsed time as approval.
Protect local approval files from the agent; same-UID development profiles are not
production isolation.
The playground also provides authenticated replacement review for an expired concrete
plan from completed research. It links a new request to the exact saved task/output and
proposal under the local inbox lock, requires fresh approval, and rejects responses to
superseded requests. Polling never renews that review or launches research again. This
review grants plan admission only, not renewed deployment or exposure authority.

## Isolated rehearsal and separately authorized live validation

Use a fresh versioned database and disposable product; preserve all historical records.
Do not operate the live shop as part of library tests. First prove approved reads, trusted
check invocation, evidence writing, allowed controls, denied scope escalation, native
stop fencing and a fresh-session recovery with the actual runner/profile.

After separate authorization, use a new short frozen plan and sufficient traffic:

1. Complete research → checked/instrumented candidate → bounded canary → zero → separate
   fixed main → zero/mature readout → authorized disposition/observation → retained learning.
2. Repeat with lost launch/activation response and worker interruption. Require original
   task/operation/deadline, no duplicate allocation and no manual state repair.
3. Inject transient then sustained monitoring failures, stop races and one authorized
   repair. Require protected zero, fresh repair identities and preserved accepted baseline.
4. Reopen/audit and record versions, receipts, costs and every intervention. Completion
   requires settled effects and learning; passing fixtures or surviving several days is
   not a successful live cycle or production qualification.

## Optional local manager

The [manager integration guide](manager.md) defines optional async approval and
metrics adapters. These use the host-authenticated operator and authoritative host
records. The UI adds no permission system, statistics engine, or stop executor.
