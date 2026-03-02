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

Use `zed-agentops-init.sh` to scaffold a directory (it creates `.rules`, `.zed/`, `.agent`, and `.zed/scripts/verify`, plus `.agent/journal.jsonl`, `.agent/snapshot.json`, `.agent/checkpoint.json`).
It also auto-appends common entries to `.gitignore`.
Open the directory in Zed and use the Agent Panel.
For release coverage runs, use `.zed/scripts/verify-release` (requires `pytest-cov`).

## Where things live

- `.rules` : project rules auto-injected into Zed Agent context
- `.zed/tasks.json` : reusable Tasks (verify, git helpers)
- `.zed/scripts/verify` : the single entry point for build/test/lint (extend as needed)
- `.zed/scripts/verify-release` : release-only coverage run (pytest-cov)
- `.agent/journal.jsonl` : append-only event log
- `.agent/snapshot.json` : state snapshot
- `.agent/checkpoint.json` : roll-forward start
- `/opt/homebrew/bin/agentops_mcp_server` : MCP server binary installed by Homebrew (macOS)

## MCP Server (Zed)

The MCP server is provided as a Homebrew-installed binary (e.g. `/opt/homebrew/bin/agentops_mcp_server`) and exposes a minimal JSON-RPC 2.0 stdio protocol compatible with Zed. It reads one JSON object per line from stdin and writes JSON-RPC responses to stdout. Supported methods include `initialize`, `initialized`, `tools/list`, `tools/call`, `shutdown`, and `exit`.



Zed (MCP Server):
```json
{
  "agentops-server": {
    "command": "/opt/homebrew/bin/agentops_mcp_server",
    "args": [],
    "env": {}
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
- Aliases: dotted names (e.g. `roll_forward.replay`) map to snake_case for compatibility.

Usage notes:
- Call `tools/list` to enumerate tools. Example request: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- Call `tools/call` to invoke a tool. Example request: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"journal_append","arguments":{"kind":"task.start","payload":{"title":"Review v0.1.0 docs"}}}}`
- Successful responses include a `result`; failures include an `error` with `code` and `message`.

Then register the MCP server in Zed and grant tool permissions as you prefer.

## License
MIT
