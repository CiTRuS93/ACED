# Documentation

The root [README](../README.md) describes the shipped development preview. These
guides explain its responsibilities, host contract, and qualification limits.

## Start with the problem you want to solve

| Your question | First check | What a pass establishes |
| --- | --- | --- |
| Did a lost launch response cause duplicate work? | [Workflow recovery](examples/resume-workflow.md) | One fixture invocation, then observation after reopening SQLite in the same process |
| Can a pending approval survive process exit? | [Approval wait](examples/persist-approval.md) | A second process recovers the original proposal and waits without launching |
| Does the next cycle receive prior learning? | [Synthetic experiment](examples/synthetic-experiment.md) | Two fixture cycles, separated canary/main exposure and retained source/learning |
| What does the operator see? | [Offline manager](manager.md#offline-demonstration) | A local browser journey through synthetic approvals, observations and history |

Choose one, check its expected output, then read its integration boundaries before
connecting a product. None of these checks qualifies production credentials,
real-user exposure or unattended operation.

## First-run checklist

For any of the three Python examples, use Python 3.12+ and a terminal in a source
checkout's root (the directory containing `pyproject.toml` and `examples/`).
The commands below use a POSIX shell:

```bash
python --version
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/resume_workflow.py
```

The recovery example should end with:

```text
Original execution observed: completed; 0 duplicate launches
Next stage: implement; audit valid: True
```

Use the same environment for `examples/persist_approval.py` or
`examples/synthetic_experiment.py`; their guides show the complete expected output.
The core has no runtime dependencies. Installation may download build tooling;
the examples themselves need no network, coding CLI or credentials and deploy
nothing. Each creates and removes a disposable database, so rerunning starts a
new demonstration rather than recovering a previous example run.

- **Python is older than 3.12:** select an installed Python 3.12+ interpreter when
  creating the environment. Check its version before installing.
- **`pyproject.toml` or the example file cannot be found:** change to the checkout
  root. These commands assume source files, not only an installed wheel.
- **`ModuleNotFoundError: aced`:** install with the same `.venv/bin/python` used to
  run the example. Do not substitute an unrelated system interpreter.
- **An assertion or unexpected result appears:** preserve the command, Python
  version, commit and redacted output for diagnosis. Do not remove assertions or
  alter stored state to obtain a pass. The [contribution guide](../CONTRIBUTING.md)
  explains safe bug reports; exclude credentials and runtime databases.

On Windows, the virtual environment's interpreter is `.venv\Scripts\python.exe`
instead of `.venv/bin/python`. The coding CLI runners initially target Linux;
a portable fixture pass does not qualify a live runner on another platform.

The browser demo has additional Node/build requirements, described in its
[own setup](manager.md#offline-demonstration). It is optional for the core checks.

## After the first check

- Read the [Python composition example](runtime.md#run-an-offline-example) to see
  how the runtime, identity provider, infrastructure and runner fit together.
- Follow the [host integration guide](integrations.md) before replacing fixtures:
  your host owns identity, authorization, tool effects, authoritative evidence and
  independently available stopping. ACED is not a per-tool permission interceptor.
- Use the [onboarding sequence](designs/new-user-onboarding.md) and
  [qualification roadmap](roadmap.md) for rehearsal and remaining live checks.

The separately maintained playground is not included in this repository or
package; see [example availability](integrations.md#example-availability).
Install from this source checkout for these instructions; they do not require a
package-index release.

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
