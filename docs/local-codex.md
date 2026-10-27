# Codex CLI runner

`CodexCliRunner` implements the same `AgentRunner` contract as any other agent.
The lifecycle does not contain Codex-specific stages. A project can use Codex for
all tasks or select different registered runners for individual steps.
See [coding agent CLIs](agent-clis.md) for Claude Code, Cursor and OpenCode configuration.

This adapter uses **`codex exec`**, not the Codex SDK. The host installs and
provisions the CLI in a trusted execution environment. The development tests use
a disposable test executable; live Codex execution and isolation remain separate
qualification work.

## Host configuration

```python
from pathlib import Path

from aced.codex import CodexCliRunner

runner = CodexCliRunner(
    state_directory=Path("/srv/aced/agent-jobs"),
    output_directory=Path("/srv/aced/agent-output"),
    executable=("/usr/local/bin/codex",),
    env={
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/srv/aced/agent-home",
        "CODEX_HOME": "/srv/aced/agent-home/.codex",
    },
    tool_profiles={
        "research": "read-only",
        "editing": "workspace-write",
    },
)
```

These example paths must exist in the host environment. Authentication and connected
tools belong in the dedicated host-controlled configuration. `env` is passed
explicitly; the service environment is not merged into it and it is not persisted
in task receipts. Supply any additional tool-specific variables through the host's
credential mechanism, never in task context.

Keep the state directory outside the agent workspace and deny agent access.
It contains prompts, retained outputs, event logs, and durable execution records.
An optional separate `output_directory` exposes the schema and final response
surface to the child without exposing recorder state. The recorder copies the
response into private storage after the original child exits. The host must also
protect its CLI configuration and permission profile from agent writes. Filesystem
permissions by themselves do not isolate processes that share a user identity.

A `launcher_prefix` may wrap the CLI command in host-managed isolation. It is an
argument sequence, not a shell string. The library's CLI sandbox selection is an
additional control; it is not a substitute for the host's process, filesystem,
network, tool, and credential isolation.

Named tool profiles map to the CLI's `read-only` or `workspace-write` sandbox.
Without an override, the default profile uses `workspace-write` for implementation
and `read-only` for other steps. Profiles do not themselves grant remote tool
permissions or configure approvals. The host must prepare the appropriate tools
and enforce their authority.

## Task invocation

The runner passes arguments directly without shell interpolation. It invokes
`codex exec` with JSON event output, an explicit sandbox, a final-output file,
and the workspace. The prompt arrives on standard input with the frozen output
schema. Closed schemas also use the CLI's native `--output-schema` flag; schemas
with open objects, such as the runtime's deliverable and checkpoint envelope,
use the prompt contract because the provider's strict format rejects those shapes.
Both paths require valid final JSON and independent validation against the same
frozen task schema before reporting completion.
Each task receives explicit source, goal, evidence, learning, purpose and scope context.
It returns the [four-stage result envelope](designs/four-stage-agent-contract.md),
including a checkpoint and named dependency when yielding. Fresh sessions are the
required recovery fallback; no native conversation continuation is needed.

The runner keeps the task fingerprint and stable execution identity. It validates
the final JSON independently against the supported schema subset. Structured output
is a proposed result; `Infrastructure.read_evidence` must establish the authoritative facts
before the coordinator advances.

The runner reports monetary usage as unknown. `StepConfig.max_cost` is an envelope
for host-enforced spending, not a claim that the CLI adapter measures or enforces
monetary cost. The host must apply its own quotas and accounting.

## Recovery and cancellation

A small detached recorder captures completion independently of the coordinator's
lifetime. Starting an already recorded identical task returns its existing reference;
changed input under the same task ID is rejected. Observation never launches a job.

If a launch intent exists without a live recorder or a terminal receipt, the outcome
is unknown. The runner does not launch a replacement or resume an unrecorded session.
Host reconciliation is required before a new attempt can be considered safe.

Cancellation writes a request for the original recorder. It remains pending or
unknown until termination is confirmed. The recorder is a development convenience,
not a general process supervisor. The host still owns containment of descendants
and recovery after host failure. Cancelling the CLI cannot establish that deployment,
exposure, or other external effects have ended.

Use a fresh task with explicit context for the next lifecycle step. This adapter
does not depend on cross-task conversation history and does not silently select or
resume another Codex session.

## Qualification

Before admitting this runner to a real integration, pin and record the installed
CLI version and verify actual command flags, authentication, tool availability,
structured output, timeouts, cancellation, and restart behavior in the selected
host environment. Verify isolation with the real tools and credentials, not only a
fake CLI process. The [roadmap](roadmap.md) separates these checks from offline
contract tests and operational qualification.
