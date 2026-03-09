# Zed AgentOps

Zed AgentOps helps you run an edit → verify → commit loop inside Zed with an MCP server and a project scaffold designed for resumable agent work.

> Currently supported on macOS.

## What it does

- Scaffolds a project for AgentOps use in Zed
- Provides a local MCP server for repo, verification, and resume-oriented workflow helpers
- Adds a default `verify` entry point you can extend for your project
- Keeps enough local state for the agent to resume work more reliably across interrupted sessions

This README is written for users of the tool. Internal implementation details are intentionally kept to a minimum.

## Installation

Install with Homebrew:

```bash
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

This installs the `agentops_mcp_server` binary and `zed-agentops-init.sh`.

## Quick start

Initialize a new project directory:

```bash
zed-agentops-init.sh my_project
```

Update an existing AgentOps-managed directory:

```bash
zed-agentops-init.sh --update my_project
```

After initialization:

1. Open the directory in Zed
2. Register the MCP server in your Zed settings
3. Open the Agent Panel
4. Start working in the repo

## What initialization creates

Running `zed-agentops-init.sh` sets up the files you need to start using AgentOps in Zed:

- `.rules`
- `.zed/tasks.json`
- `.zed/scripts/verify`
- `.agent/tx_event_log.jsonl`
- `.agent/tx_state.json`

The baseline `.agent/tx_state.json` is intentionally a normalized empty-transaction state. It includes the canonical top-level fields and metadata needed for normal runtime interpretation, including:

- `schema_version` for the transaction state format
- `active_tx` initialized to the safe `none` / `planned` baseline
- `last_applied_seq`
- `integrity.state_hash`
- `integrity.rebuilt_from_seq`
- `integrity.drift_detected`
- `integrity.active_tx_source`
- `updated_at`

This baseline is meant to be compatible with the richer runtime-rebuilt state shape without inventing runtime-only facts that can only be known after canonical event replay.

It also:
- creates a Git repository if one does not already exist
- appends common ignore entries to `.gitignore`
- preserves existing files when possible
- supports `--update` to refresh an existing setup

## Recommended Zed configuration

Add the MCP server to your Zed settings.

Minimal MCP server example:

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

If you also want to pre-allow commonly used AgentOps tools in the Agent Panel, your `settings.json` can include entries like this under your tool permissions:

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

Adjust permissions to match your own security preferences.

## Typical usage flow

Once the project is initialized, the normal flow is:

1. Ask the agent to make a change
2. Let it run project verification
3. Review the result
4. Commit the change

The scaffolded verify script is the default entry point for checks:

```bash
.zed/scripts/verify
```

Extend it to match your repository. By default, it tries common checks for changed files, such as Python, Swift, Rust, shell scripts, and Bicep where the corresponding tools are installed.

## Release verification / coverage

For release-oriented Python coverage runs, use:

```bash
.zed/scripts/verify-release
```

This requires `pytest-cov` to be available.

## Updating from older versions

If you already use Zed AgentOps, run:

```bash
zed-agentops-init.sh --update <project>
```

This refreshes the user-facing scaffold, especially:

- `.rules`
- `.agent` state file presence
- default verify/task scaffolding where applicable

Recent versions also tightened resumability and state alignment, so updating is recommended before starting new work in an older scaffold.

## What changed in recent versions

### Current behavior summary

- The scaffold now aligns `.rules` with the current workflow expectations
- Initial transaction state starts from a normalized baseline shape
- Resume behavior is centered on the local AgentOps state files
- The default setup is aimed at safer interruption/resume cycles

### Version concepts

AgentOps exposes a few different version concepts, and they do not mean the same thing:

- package/server version: the released MCP server implementation version
- transaction/schema version: the version of the persisted `tx_state` structure
- draft/release-plan version: the workflow planning or documentation version used in `docs/`

Keeping these distinct helps avoid confusion when the server implementation, the transaction state schema, and a draft release plan evolve on different timelines.

### If you are upgrading from an older scaffold

You may notice:

- refreshed `.rules`
- refreshed initial state defaults
- improved consistency between the scaffold and the current runtime behavior

In most cases, `--update` is enough.

## Files you will commonly interact with

- `.rules` — project instructions injected into the agent context
- `.zed/scripts/verify` — your main verification entry point
- `.zed/tasks.json` — reusable Zed tasks
- `.agent/tx_event_log.jsonl` — local AgentOps event log
- `.agent/tx_state.json` — local AgentOps state used for resuming work

For most users, the important point is simple: keep `.rules` current by using the latest scaffold or running `--update`.

For a release-facing explanation of the supported v0.5.0 client/server contract, see `docs/v0.5.0/interoperability.md`. That guide summarizes what is enforced by the server, what is exposed as helper behavior, and what remains client-side operating convention.

## Notes

- macOS only at the moment
- The generated scaffold is meant to be customized per repository
- The default verify script is intentionally conservative and may need project-specific additions

## License

MIT