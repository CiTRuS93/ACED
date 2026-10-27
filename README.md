# ACED

**Agentic Continuous Experimentation and Development**

An open-source Python framework implementing the
Continuous Data-Driven AI Development paradigm. It coordinates coding
agents through product experiments with durable progress, verified evidence, and
human-controlled approvals.

> Hypothesize → Implement → Experiment → Decide → Repeat

ACED records each agent task before launch, waits for approvals and verified
outcomes, and carries accepted source and learning into the next cycle. Use your
existing product tools and choose **Codex, Claude Code, Cursor, or OpenCode** per step.

**Development preview:** no production credentials, real-user exposure, or unattended
operation are qualified. Fixture tests do not establish live integration safety.

## Try the offline demo

![Offline manager showing the four stages, a completed fixture experiment, and retained inconclusive results.](docs/images/manager-offline-demo.png)

Explore approvals, experiment observations, and learning in the local browser
console. This demo uses deterministic agents and synthetic metrics; it needs no
agent account, credentials, or product connection.

Requires Python 3.12+. For a source checkout, also install Node 22.12+ and a current
npm. Download or clone this repository and open a terminal in its root directory
(the directory containing `pyproject.toml`), then run:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[manager]'
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/aced-manager-demo
```

Open the printed local URL, select the welcome run, and review tasks under
**Approvals**. Follow the canary and main observations under **Experiment**, then
inspect **Cycle history** and continue with retained learning. The fixture ends
with an inconclusive readout and retains its baseline. Restarting the demo resets
its in-memory state. Nothing is deployed and no product traffic is sent.

The [manager guide](docs/manager.md) also covers installing a built wheel, which
includes the browser assets and does not need Node at runtime.

For a terminal-only check, create the virtual environment above and install the
core with `.venv/bin/python -m pip install -e .`. Run
`.venv/bin/aced --database :memory: conformance`. Expected output:

```json
{"audit_valid":true,"cycles":2,"kind":"deterministic fixture","passed":true,"tasks":12}
```

The core has no runtime dependencies. Try the [complete offline Python example](docs/runtime.md#run-an-offline-example)
to see how the library is embedded. Linux is the initial platform for coding CLI runners.

## What it does

- Resumes from durable task records after interruptions; uncertain work is observed before another launch is allowed.
- Waits for host-enforced approvals and authoritative evidence, without keeping an agent running during the wait.
- Separates a bounded safety canary from the product experiment, requiring confirmed zero exposure between them and before readout.
- Retains checked source, experiment outcomes, and learning for later cycles, with an audited SQLite history.

See the [playground example](docs/playground-example.md): a real Codex agent tests
catalog ordering against synthetic shop traffic. The October 24 snapshot reaches
the main experiment; its final readout is not included and no benefit result is claimed.

## What you integrate

This preview is for developers exploring agent-driven experiments on products that
already have testing, deployment, measurement, and exposure controls. Supply a
repository, measurable goal, experiment plan, isolated agent environment,
and access to those existing tools.
Agents perform the recurring work with those tools. Your host authorizes each task
and verifies returned references against actual source, checks, deployments, and
experiment outcomes.

Your infrastructure owns tool permissions, approval gates, external action
idempotency, statistical validity, and an independently available emergency stop
executor. ACED does not intercept every tool call or replace those systems.
Every gate can use human approval, scoped preauthorization, or denial.
The separate playground host supplies its own approval and check helpers; that
checkout is not included here. The offline demo above is included in this repository.

A scheduling hold and a runtime shutdown do not stop exposure. Product stopping
and rollback need confirmed outcomes; an agent's statement is insufficient.
The [integration guide](docs/integrations.md) gives the complete host contract.

## Compatibility

The package and commands are now `aced`, with `aced-manager-demo` for the offline
manager. The previous `cddai` imports and CLI commands remain compatibility aliases.
Existing `cddai-four-stage-1` databases keep their format and history unchanged.

This implementation replaces the earlier preview's Framework and provider APIs.
**Use a fresh database for earlier formats.** Those databases require the earlier
package; their history is not migrated or silently rewritten. Vendor adapters,
alternate stores, and the former generic provider platform are no longer maintained.

## Documentation

- [Documentation starting points](docs/README.md)
- [Design and rendered charts](docs/design.md)
- [Product integration](docs/integrations.md)
- [Runtime](docs/runtime.md) and [coding agent CLIs](docs/agent-clis.md)
- [Qualification roadmap](docs/roadmap.md)
- [Contributing](CONTRIBUTING.md)
