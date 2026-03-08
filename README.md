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

It also:
- creates a Git repository if one does not already exist
- appends common ignore entries to `.gitignore`
- preserves existing files when possible
- supports `--update` to refresh an existing setup

## Recommended Zed configuration

Add the MCP server to your Zed settings.

Example:

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

You can then grant tool permissions in Zed according to your preferences.

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
- Initial transaction state starts from the current baseline
- Resume behavior is centered on the local AgentOps state files
- The default setup is aimed at safer interruption/resume cycles

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

## Notes

- macOS only at the moment
- The generated scaffold is meant to be customized per repository
- The default verify script is intentionally conservative and may need project-specific additions

## License

MIT