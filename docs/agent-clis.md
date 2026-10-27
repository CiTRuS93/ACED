# Coding agent CLI runners

ACED includes `CodexCliRunner`, `ClaudeCliRunner`, `CursorCliRunner` and
`OpenCodeCliRunner`. All implement the async `AgentRunner` contract and share the
same durable launch, observation and cancellation machinery. Install and authenticate
each CLI separately; no vendor SDK or new runtime dependency is required.

These are Linux development-preview adapters. Tests exercise actual subprocesses
with model-free CLI stand-ins. They do not qualify installed vendor binaries,
accounts, isolated tool access, production credentials or unattended operation.

## Register and route runners

Compose runners in host Python code, using a dedicated environment for each CLI:

```python
from dataclasses import replace
from pathlib import Path

from aced import (
    ClaudeCliRunner,
    CursorCliRunner,
    OpenCodeCliRunner,
    Step,
    StepConfig,
)

# The host supplies these environment mappings, including credential references.
# Nothing from the service's environment is inherited implicitly.
runners = {
    "claude": ClaudeCliRunner(
        Path("/srv/aced/jobs/claude"),
        executable=("/usr/local/bin/claude",),
        env=claude_environment,
        tool_profiles={"research": "plan", "editing": "acceptEdits"},
    ),
    "cursor": CursorCliRunner(
        Path("/srv/aced/jobs/cursor"),
        executable=("/usr/local/bin/agent",),
        env=cursor_environment,
        tool_profiles={"research": "ask", "editing": "agent"},
    ),
    "opencode": OpenCodeCliRunner(
        Path("/srv/aced/jobs/opencode"),
        executable=("/usr/local/bin/opencode",),
        env=opencode_environment,
        tool_profiles={"research": "plan", "editing": "build"},
    ),
}

# Given the host's existing ProjectConfig, route implementation to Cursor.
project = replace(
    project,
    default_agent="claude",
    steps={
        **project.steps,
        Step.IMPLEMENT: StepConfig(agent="cursor", tool_profile="editing"),
    },
)
# Pass runners and project into Runtime as in the runtime guide.
```

The runtime freezes the selected registered runner and profile per task. Changing
future routing cannot transfer an existing execution to a different CLI. Use a
separate protected state directory for each runner configuration and retain it
across coordinator restarts. An existing identical task returns its original
reference; conflicting inputs or CLI adapter identity are rejected.

## CLI contracts and permissions

| Runner | Invocation | Default profile | Explicit profile values |
| --- | --- | --- | --- |
| Codex | `codex exec` | Implementation: `workspace-write`; otherwise `read-only` | `read-only`, `workspace-write` |
| Claude Code | `claude --print --output-format json --json-schema …` | `dontAsk` | `dontAsk`, `plan`, `acceptEdits` |
| Cursor | `agent --print --output-format stream-json --workspace …` | `agent` | `agent`, `ask`, `plan` |
| OpenCode | `opencode run --format json --agent …` | Implementation: `build`; otherwise `plan` | `build`, `plan` |

Correction tasks use the conservative Codex/OpenCode default even during
implementation. Named profiles are host-selected native CLI options; they are
**not interchangeable isolation guarantees**. Unknown profile names are rejected.
Claude `dontAsk` denies tools needing approval unless already allowed by host rules;
`acceptEdits` grants the CLI's native edit permission. Cursor's default adds no
force, workspace-trust or MCP-approval bypass. The host must prepare its permission
allow/deny rules and workspace trust. OpenCode's native agents use the host's
configured tool permissions; pending interactive permission requests in the
researched `run` protocol are rejected. No adapter grants unrestricted permissions
or resumes an existing native conversation automatically.

The recorder launches the CLI in the task workspace with the exact supplied `env`.
Pass authentication and model/provider configuration through host-controlled CLI
settings or environment, never task context. `executable` and `launcher_prefix`
are argument sequences, without shell interpolation. The latter can invoke a
host-managed isolation wrapper. The host must protect CLI settings, credentials,
runner records, source boundaries and native tool authority. Prompt instructions
and native modes do not enforce those boundaries.

Each CLI receives the frozen task prompt and output schema through stdin. Claude
also receives its native schema flag. Cursor and OpenCode are instructed to return
one plain JSON object; their CLI JSON formats only describe the transport, so
they do not guarantee schema-conforming task output. The adapters independently
validate the resulting object against the same supported schema subset as Codex.

Claude requires an explicit successful result with `structured_output`. Cursor
requires an explicit successful terminal result and valid task JSON in the final
assistant message after tool work. Its aggregate `result` text may include progress
narration, so the adapter extracts the final message from the event stream instead.
OpenCode requires a completed final step with reason `stop`, consistent native
session/message identities, and JSON text from that final message. Progress text
is excluded. Provider errors, denied/failed tools reported by Claude/OpenCode,
deferred work, missing completion signals, invalid JSON and schema mismatch cannot
produce a completed task. No output repair or retry is performed. A well-formed
task envelope can still yield a durable waiting/blocked result through the runtime.

The host must verify all claimed product outcomes with `Infrastructure.read_evidence`.
Native session IDs and token diagnostics are retained for inspection; monetary usage
remains unknown. The host enforces spending independently of `max_cost` prompt text.

## Recovery and qualification

The detached recorder bounds stdout/stderr, enforces the deadline, retains private
output and records the original process result. It survives a coordinator restart.
Observation never launches a replacement. An intent without a live recorder or
valid receipt stays unknown and requires host reconciliation. Cancellation requests
local CLI termination; it does not establish descendant termination or settled
external effects. The host supplies process supervision and independent stopping.

New stdout-based adapters publish their output directly from the recorder into
protected storage; they need no agent-writable output directory. Codex's separate
output-file surface and configuration are described in the [Codex guide](local-codex.md).
All retained prompts and logs need host access control and retention/redaction policy.

The command contracts were checked against the official
[Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
[Claude headless guide](https://code.claude.com/docs/en/headless),
[Cursor parameters](https://cursor.com/docs/cli/reference/parameters),
[Cursor output format](https://cursor.com/docs/cli/reference/output-format),
[Cursor permissions](https://cursor.com/docs/cli/reference/permissions), and
[OpenCode CLI reference](https://opencode.ai/docs/cli/).
OpenCode event decoding follows the
[v1.14.19 run implementation](https://github.com/anomalyco/opencode/blob/v1.14.19/packages/opencode/src/cli/cmd/run.ts);
this does not assert compatibility with a different major-version protocol.

Pin and record the installed CLI version, then verify its flags, authentication,
permission denial, structured result, cancellation, restart and isolation behavior
with the real host tools before qualifying that integration. See the
[runtime guide](runtime.md), [host contract](integrations.md) and
[qualification roadmap](roadmap.md).
