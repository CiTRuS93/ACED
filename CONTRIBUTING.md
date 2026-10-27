# Contributing

Small, reproducible contributions are welcome. Useful starting points include:

- Try the [offline manager demo](docs/manager.md) from a fresh checkout and improve
  any unclear setup instructions. Include your Python, Node and npm versions in a report.
- Add a focused regression for a demonstrated restart, approval, evidence-validation
  or uncertain-outcome defect, with a minimal failing example.
- Improve an integration example or qualification checklist for one concrete host
  and CLI version. Keep fixture results separate from actual live integration evidence.
- Clarify a confusing term or diagram while preserving the boundaries in the
  [design](docs/design.md).

For a bug report, include exact versions, reproduction steps, expected behavior and
redacted observed output. Do not attach credentials, private prompts or runtime
databases. Discuss a proposed new integration or larger feature with its concrete
consumer and the [qualification roadmap](docs/roadmap.md) before building it.

## Development setup and checks

Use Python 3.12 or newer. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

The manager and release builds also need Node.js 22.12+ and the modern npm bundled
with Node. Check `node --version` and `npm --version` to catch an older global npm
on your PATH. Run the [manager development checks](#manager-development-checks)
before the full Python suite or release packaging so the frontend assets exist.
The smaller `.[manager]` extra runs the demo without contributor tooling.

Iterate with the narrowest relevant tests. Before handing off changes to lifecycle,
persistence, public contracts, identity, or packaging, run:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov=aced --cov-branch --cov-fail-under=90
python -m build
aced --database :memory: conformance
```

Run `uv lock --check` after packaging changes when available. CI targets Linux with
Python 3.12/3.13. No live agent credentials are required by the ordinary test suite.

Keep local databases, credentials, environments, build/coverage output, caches,
temporary reviews, planning transcripts and checkpoint archives out of the public
repository. Store runtime evidence and recovery backups outside the checkout;
keep lasting design decisions in `docs/design.md` and `docs/designs/`. Inspect
`git status --short` before committing, including new files. `.gitignore` protects
common local artifacts, but does not remove files already tracked by Git.

Lifecycle changes require legal and forbidden transition tests, plus restart and
uncertain-outcome recovery cases when external work is involved. Storage changes
must preserve atomicity, revision checks, fencing, audit integrity, and rejection of
incompatible databases. Never rewrite historical records to satisfy a new schema.

Runner changes require contract tests for starting, observing without redispatch,
cancellation, structured output, deadlines, stale/mismatched identities, and
uncertain completion. Codex CLI process tests use a disposable test executable;
they do not establish real Codex isolation or production credential safety.

Evidence tests should demonstrate that old checks, mismatched artifacts, agent claims,
and unknown stop status cannot advance a run. Test independent stop reporting,
canary/experiment separation, and accepted-source/learning continuity.

Keep integration requirements explicit. The host's permission and product systems
own external tool effects; the task outbox owns agent invocation intent. Avoid
adding adapters or protocols with no consumer in the agreed journey.

Report fixture conformance, live integration tests, and operational qualification
separately. Passing one is not evidence for all three. Priorities follow the
[roadmap](docs/roadmap.md) and [design](docs/design.md).

Four-stage changes also require both normal-expiry poll orderings, lost activation and
fresh-session recovery, scope-bound approvals, stop delivery/fencing, observability,
linked candidate/repair continuity and finite output correction. Persistence changes
run the 1,250/2,500-task linear-growth/reopen fixture; report actual bytes/time separately
from live operating claims. Companion host tests remain in `cddai-playground/host_tests`
and are not part of the independent product's default test suite.

## Manager development checks

Use Node 22.12+ and a modern npm with `npm ci` support. Before Python tests or
release packaging:

```bash
cd frontend
npm ci
npm run format:check
npm run build
npm test
cd ..
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/manager/run_browser.py
```

The build writes ignored assets under `src/aced/manager/static`; wheels include
them. The source distribution includes frontend sources and lockfile; building a
wheel from it requires Node and npm registry access when dependencies are absent.
Clean release builds must build the frontend before packaging; do not reuse stale
assets. Browser tests use only the disposable fixture on an available loopback port and save
screenshots under `/tmp`. CI installs Chromium system dependencies as well.
Keep frontend dependencies and `uv.lock` current, and run `uv lock --check` after
packaging edits. Core imports must remain usable without the manager extra.

After `python -m build`, verify the installed assets with
`.venv/bin/python tests/manager/wheel_smoke.py dist/*.whl`.
