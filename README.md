# Obsoleted

# Zed AgentOps

Zed AgentOps helps you run an edit → verify → commit workflow inside Zed with a local MCP server and a project template designed for resumable agent work.

> Currently supported on macOS.

## What it does

- Creates a project template for using AgentOps in Zed
- Provides a local MCP server for repository, verification, and resume-oriented workflow helpers
- Adds default `verify` and `verify-release` entry points that you can extend for your project
- Keeps enough local state for the agent to resume work more reliably across interrupted sessions
- Aligns the generated project template, runtime workflow rules, and helper behavior around the supported v0.5.4 contract

This README is written for users of the tool. It focuses on how to set up and use AgentOps in practice.

## Installation

Install with Homebrew:

```bash
brew intall rioriost/tap/agentops_mcp_server
```

This installs:

- `agentops_mcp_server`
- `zed-agentops-init`

## Usage

### Zed configuration

Before you start using AgentOps in a project, configure Zed to use the MCP server.

For v0.5.4, this is effectively required. The intended workflow assumes:

- the MCP server is registered in Zed
- the Agent Panel can call the AgentOps tools it needs
- the commonly used AgentOps tools are pre-allowed in tool permissions

Add the MCP server to your Zed settings:

```json
{
  "agentops-server": {
    "command": "/opt/homebrew/bin/agentops_mcp_server",
    "args": [],
    "env": {
      "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
  }
}
```

Then allow the MCP tools the workflow depends on. A practical baseline is:

```json
{
  "terminal": {
    "default": "allow"
  },
  "mcp:agentops-server:workspace_initialize": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_event_append": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_state_save": {
    "default": "allow"
  },
  "mcp:agentops-server:tx_state_rebuild": {
    "default": "allow"
  },
  "mcp:agentops-server:session_capture_context": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_verify": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_commit": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_status_summary": {
    "default": "allow"
  },
  "mcp:agentops-server:repo_commit_message_suggest": {
    "default": "allow"
  },
  "mcp:agentops-server:tests_suggest": {
    "default": "allow"
  },
  "mcp:agentops-server:tests_suggest_from_failures": {
    "default": "allow"
  },
  "mcp:agentops-server:commit_if_verified": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_compact_context": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_handoff_export": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_resume_brief": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_start_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_update_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_end_task": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_add_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_update_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_complete_file_intent": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_capture_state": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_task_summary": {
    "default": "allow"
  },
  "mcp:agentops-server:ops_observability_summary": {
    "default": "allow"
  }
}
```

Adjust permissions to match your own security preferences, but if these tools are blocked the intended workflow will be incomplete.

### Machine-readable workflow responses

In v0.5.4, lifecycle-aware responses are intended to be machine-readable enough for an agent or client to decide what to do next without relying only on prose.

For lifecycle-relevant success responses, the normalized guidance fields include:

- `ok`
- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `requires_followup`
- `followup_tool`
- `active_tx_id`
- `active_ticket_id`

When the information is available, responses may also include contextual fields such as:

- `current_step`
- `verify_status`
- `commit_status`
- `integrity_status`
- `can_start_new_ticket`
- `resume_required`

These fields describe the resulting canonical state after the tool completes. In other words, they are meant to tell you whether you should begin, resume, verify, commit, explicitly end the task, or stop because the canonical state is blocked.

Lifecycle- and state-related failures are also intended to expose structured recovery guidance. The normalized failure shape includes:

- `ok: false`
- `error_code`
- `reason`
- `recoverable`
- `recommended_next_tool`
- `recommended_action`

When known, failure responses may also include canonical state or integrity context, such as the current status or phase, the active transaction identity, terminality, and integrity-related metadata.

A practical way to interpret the main fields is:

- `canonical_status` and `canonical_phase` describe the resulting canonical transaction state
- `next_action` describes the next lifecycle step that should be taken
- `terminal` tells you whether the transaction is already terminal
- `requires_followup` tells you whether more lifecycle work is still required
- `followup_tool` identifies the explicit follow-up tool when one is required

Helper completion does not always mean the transaction is finished. In particular, successful commit helpers may leave the transaction in non-terminal `committed`, which still requires explicit terminal closure such as ending the task with `done` or `blocked`.

### Initialize a project with `zed-agentops-init`

Create or update an AgentOps-managed project with:

```bash
zed-agentops-init my_project
```

or:

```bash
zed-agentops-init --update my_project
```

Use `--update` when you already have an older AgentOps template and want to refresh it to the current workflow contract.

#### What initialization creates

Running `zed-agentops-init` sets up the files you need to start using AgentOps in Zed:

- `.rules`
- `.zed/tasks.json`
- `.zed/scripts/verify`
- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

It also:

- creates a Git repository if one does not already exist
- appends common ignore entries to `.gitignore`
- preserves existing files when possible
- supports `--update` to refresh an existing setup

The baseline `.agent/tx_state.json` is intentionally a normalized empty-transaction state. It includes the major top-level fields and metadata needed for normal runtime interpretation, including:

- `schema_version`
- `active_tx`
- `last_applied_seq`
- `integrity.state_hash`
- `integrity.rebuilt_from_seq`
- `integrity.drift_detected`
- `integrity.active_tx_source`
- `updated_at`

This baseline is designed to be compatible with the richer runtime-rebuilt state shape without inventing runtime-only facts that can only be known after canonical event replay.

### Open the project in Zed

After initialization:

1. Open the project directory in Zed
2. Make sure your MCP server configuration is active
3. Open the Agent Panel
4. Confirm the agent can access the required AgentOps tools
5. Start work from the initialized repository root

For the supported workflow, the agent should initialize the workspace root before root-dependent operations and should treat `.agent/tx_state.json` and `.agent/tx_event_log.jsonl` as the canonical local workflow state.

The intended interpretation of lifecycle-aware responses is tied to that canonical state. Clients should rely on the structured response fields to understand whether there is an active transaction to resume, whether a new ticket can start safely, and whether helper success still leaves explicit follow-up work.

### Configure `verify` / `verify-release` as needed

The generated template includes:

- `.zed/scripts/verify`
- `.zed/scripts/verify-release`

The default `verify` script is intentionally conservative. Extend it to match your project.

A common Python-oriented setup is:

- `verify`: fast local checks for day-to-day work
- `verify-release`: more complete checks for release-oriented validation

For example, in a Python project you may want:

- `.zed/scripts/verify` to run `ruff check`, `ruff format --check`, and `pytest -q`
- `.zed/scripts/verify-release` to run full coverage, such as `pytest --cov`

The default release-oriented coverage entry point is:

```bash
.zed/scripts/verify-release
```

This requires `pytest-cov` to be available if you use it for Python coverage.

### Initialize the language-specific project itself

AgentOps provides the workflow template, but it does not replace your language or package manager’s own project initialization.

For example, for a Python project with `uv` you might run:

```bash
uv init
```

Then add the checks your project needs to `.zed/scripts/verify` and `.zed/scripts/verify-release`.

Likewise, for other ecosystems you should initialize the actual project using the tools that ecosystem expects before asking the agent to make meaningful changes.

### Create a `docs` directory and write a draft

For the v0.5.4 workflow, it is useful to create a `docs` directory in the project and write a draft such as:

```text
docs/draft_0.1.0.md
```

This draft is where you describe:

- goals
- scope
- constraints
- priorities
- phases
- possible tickets

You can write the draft entirely yourself, or you can work with the AI agent to refine it. Both approaches are valid.

A practical pattern is:

1. Create `docs/`
2. Write an initial draft with the requirements you already know
3. Ask the agent to help refine the draft into a phase-oriented plan
4. If useful, maintain derived planning artifacts with the agent such as:
   - `docs/__version__/plan.md`
   - `docs/__version__/tickets_list.json`
   - `docs/__version__/pX-tY.json`
5. Use those planning files as workflow guidance while the work is in progress

A helpful way to think about the planning flow is:

- `draft.md` is the place to describe the problem, goals, scope, constraints, and priorities
- `plan.md` is the place to turn that draft into phased execution guidance
- `tickets_list.json` is a compact index of the tickets you intend to work through
- `pX-tY.json` files are optional per-ticket detail records for inputs, outputs, acceptance criteria, and notes

If you maintain ticket artifacts, a practical status set is:

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

Important v0.5.0 boundary:

- planning files under `docs/` are useful workflow artifacts
- they are not mandatory server-managed protocol state
- the server does not guarantee generation, synchronization, or validation of those planning artifacts for you
- if you choose to maintain them, keeping `tickets_list.json` and the per-ticket files in sync is recommended operating practice

They are best understood as user- or client-managed workflow documents.

## Updating from older versions

If you already use Zed AgentOps, run:

```bash
zed-agentops-init --update <project>
```

This refreshes the user-facing template, especially:

- `.rules`
- `.agent` state file presence
- default verify/task templates where applicable

Updating is recommended when moving from an older template, because recent versions tightened:

- resumability behavior
- transaction/state alignment
- workflow rule clarity
- template/runtime consistency

In most cases, `--update` is enough.

## What's new in v0.5.0

The most important user-facing changes in v0.5.0 are about clarity and predictability.

### 1. The documented workflow is closer to the real supported workflow

The main goal of v0.5.0 is to reduce mismatches between:

- `.rules`
- the generated template
- runtime server behavior
- helper tools
- release-facing documentation

As a user, that means the documented workflow is more trustworthy than before.

### 2. Ticket files are convention, not server protocol

If you keep planning files such as:

- `docs/__version__/plan.md`
- `docs/__version__/tickets_list.json`
- `docs/__version__/pX-tY.json`

they are useful workflow documents, but they are not canonical server-managed state.

In practice:

- you can maintain them manually
- you can maintain them together with the agent
- but you should not assume the server automatically creates, synchronizes, or validates them

### 3. The canonical local workflow state is under `.agent/`

For practical use, the most important canonical artifacts are:

- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

Handoff and planning docs are helpful, but they are not the canonical workflow record.

### 4. Commit workflow is more explicit

The supported flow is stricter:

- verify before commit
- no commit when there are no changes

This reduces accidental empty commits or unverified commits.

### 5. File-intent workflow is easier to use safely

The supported helper surface now includes:

- `ops_add_file_intent`
- `ops_update_file_intent`
- `ops_complete_file_intent`

These helpers make common file-intent workflows easier to follow without weakening the canonical transaction rules.

### 6. Bootstrap state is easier to reason about

The initial `.agent/tx_state.json` baseline is more normalized, so users and clients are less likely to misread missing fields as ambiguous old-template behavior.

### 7. Version concepts are intentionally distinct

You may see different version concepts, and they do not all mean the same thing:

- package/server version
- transaction/schema version
- draft/release-plan version

This is expected. Do not assume that a docs version label is automatically the same thing as the persisted transaction schema version.

### Practical recommendations for users

For day-to-day use in v0.5.0:

1. Keep your template current with `zed-agentops-init --update` when needed
2. Treat `.agent/tx_state.json` and `.agent/tx_event_log.jsonl` as the canonical local workflow state
3. Treat planning files under `docs/` as useful convention, not guaranteed server protocol
4. Extend `verify` and `verify-release` to match your project
5. Prefer small, clearly scoped drafts in `docs/` before large agent-driven work
6. Expect the agent workflow to follow initialize → change → verify → commit more strictly than before

For a fuller release-facing explanation of the supported v0.5.0 client/server contract, see `docs/v0.5.0/interoperability.md`.

## Notes

- macOS only at the moment
- The generated template is meant to be customized per repository
- The default verify scripts are intentionally conservative and may need project-specific additions
- The v0.5.0 workflow distinguishes between enforced protocol behavior and user-managed workflow convention; that distinction is intentional

## License

MIT
