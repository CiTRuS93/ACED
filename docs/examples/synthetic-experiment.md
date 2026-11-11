---
title: Run a synthetic product experiment with coding-agent tasks
description: Run an offline two-cycle fixture with synthetic tasks, canary and main experiments, and retained learning. ACED is a development preview.
---

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
