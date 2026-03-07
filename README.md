# Zed AgentOps

- CI/CD-like loop: edit -> verify -> commit
- Test generation as part of the loop (agent adds tests, then verify)

Note: This project currently supports macOS only.

## Quick start

```bash
zed-agentops-init project_name
zed-agentops-init --update existing_project
```

Use `--update` to migrate an existing AgentOps-managed directory (removes legacy files, creates `.agent` state files, and refreshes `.rules`).

## Installation

```
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

Use `zed-agentops-init.sh` to scaffold a directory (it creates `.rules`, `.zed/`, `.agent`, and `.zed/scripts/verify`, plus canonical `.agent/tx_event_log.jsonl` and `.agent/tx_state.json`, along with legacy derived-only `.agent/journal.jsonl`, `.agent/snapshot.json`, `.agent/checkpoint.json`).
It also auto-appends common entries to `.gitignore`.
Open the directory in Zed and use the Agent Panel.
For release coverage runs, use `.zed/scripts/verify-release` (requires `pytest-cov`).

## Workflow tips

- Before ending a session or when context is tight:
  - Run `ops_compact_context` (prefer `include_diff=false`, `max_chars` optional)
  - Run `ops_handoff_export` (writes `.agent/handoff.json` by default; optional path writes under `.agent`)
- To resume quickly: run `ops_resume_brief`
- Token discipline: prefer summaries/diff stats over full diffs and keep outputs short
- All MCP tools accept optional `truncate_limit` (as exposed by `tools/list`)

## Semantic resume (0.4.0)
- Canonical sources of truth are `.agent/tx_event_log.jsonl` (event log) and `.agent/tx_state.json` (materialized state).
- `semantic_summary` captures concise progress; `user_intent` records explicit resume intent (e.g., “continue”).
- `.agent/handoff.json` is derived-only and never a canonical input for resume decisions.

## About .rules (from v0.2.0)
`zed-agentops-init` generates `.rules`.

## Where things live

- `.rules` : project rules auto-injected into Zed Agent context
- `.zed/tasks.json` : reusable Tasks (verify, git helpers)
- `.zed/scripts/verify` : the single entry point for build/test/lint (extend as needed)
- `.zed/scripts/verify-release` : release-only coverage run (pytest-cov)
- `.agent/tx_event_log.jsonl` : canonical transaction event log
- `.agent/tx_state.json` : canonical materialized transaction state
- `.agent/handoff.json` : derived-only human-readable summary
- `.agent/journal.jsonl` / `.agent/snapshot.json` / `.agent/checkpoint.json` : legacy derived-only artifacts
- `/opt/homebrew/bin/agentops_mcp_server` : MCP server binary installed by Homebrew (macOS)

## MCP Server (Zed)

The MCP server is provided as a Homebrew-installed binary (e.g. `/opt/homebrew/bin/agentops_mcp_server`) and exposes a minimal JSON-RPC 2.0 stdio protocol compatible with Zed. It reads one JSON object per line from stdin and writes JSON-RPC responses to stdout. Supported methods include `initialize`, `initialized`, `tools/list`, `tools/call`, `shutdown`, and `exit`.



Zed (MCP Server):
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

Tool Settings (settings.json):
```json
"agent": {
  "tool_permissions": {
    "tools": {
      "create_directory": {
        "default": "allow"
      },
      "fetch": {
        "default": "allow"
      },
      "web_search": {
        "default": "allow"
      },
      "terminal": {
        "default": "allow"
      },
      "mcp:agentops-server:journal_append": {
        "default": "allow"
      },
      "mcp:agentops-server:snapshot_save": {
        "default": "allow"
      },
      "mcp:agentops-server:snapshot_load": {
        "default": "allow"
      },
      "mcp:agentops-server:checkpoint_update": {
        "default": "allow"
      },
      "mcp:agentops-server:checkpoint_read": {
        "default": "allow"
      },
      "mcp:agentops-server:roll_forward_replay": {
        "default": "allow"
      },
      "mcp:agentops-server:continue_state_rebuild": {
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
  },
  "default_model": {
    "provider": "copilot_chat",
    "model": "gpt-5.2-codex"
  }
},
```

MCP tools (snake_case):
- `journal_append`
- `tx_event_append`
- `tx_state_save`
- `tx_state_rebuild`
- `snapshot_save`
- `snapshot_load`
- `checkpoint_update`
- `checkpoint_read`
- `roll_forward_replay`
- `continue_state_rebuild`
- `session_capture_context`
- `repo_verify`
- `repo_commit`
- `repo_status_summary`
- `repo_commit_message_suggest`
- `tests_suggest`
- `tests_suggest_from_failures`
- `commit_if_verified`
- `ops_compact_context`
- `ops_handoff_export`
- `ops_resume_brief`
- `ops_start_task`
- `ops_update_task`
- `ops_end_task`
- `ops_capture_state`
- `ops_task_summary`
- `ops_observability_summary`
- Aliases: dotted names (e.g. `roll_forward.replay`) map to snake_case for compatibility.

Usage notes:
- Call `tools/list` to enumerate tools. Example request: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- Call `tools/call` to invoke a tool. Example request: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"journal_append","arguments":{"kind":"task.start","payload":{"title":"Review v0.1.0 docs"}}}}`
- Successful responses include a `result`; failures include an `error` with `code` and `message`.

Then register the MCP server in Zed and grant tool permissions as you prefer.

## License
MIT
