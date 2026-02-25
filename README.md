# Zed AgentOps

- Cross-session handoff (.agent/handoff.md)
- CI/CD-like loop: edit -> verify -> commit -> update handoff
- Test generation as part of the loop (agent adds tests, then verify)

## Quick start

```bash
./zed-agentops-init.sh project_name
```

Use `zed-agentops-init.sh` to scaffold a directory (it creates `.rules`, `.zed/`, `.agent`, and `.zed/scripts/verify`).
It also auto-appends common entries to `.gitignore` (including `.zed/` and `.agent/`).
Open the directory in Zed and use the Agent Panel.

## Where things live

- `.rules` : project rules auto-injected into Zed Agent context
- `.zed/tasks.json` : reusable Tasks (verify, git helpers)
- `.zed/scripts/verify` : the single entry point for build/test/lint (extend as needed)
- `.agent/handoff.md` : cross-session handoff (source of truth)
- `.agent/session-log.jsonl` : optional event log (append-only)
- `.agent/checkpoints/` : diff checkpoints (json snapshots)
- `src/agentops_mcp_server/` : optional MCP server scaffold (Python)

## MCP Server (Zed)

The MCP server lives in `src/agentops_mcp_server/main.py` and exposes a minimal JSON-RPC 2.0 stdio protocol compatible with Zed. It reads one JSON object per line from stdin and writes JSON-RPC responses to stdout. Supported methods include `initialize`, `initialized`, `tools/list`, `tools/call`, `shutdown`, and `exit`.

Run it with:
- `uv run agentops_mcp_server`

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
      "mcp:agentops-server:handoff.read": {
        "default": "allow"
      },
      "mcp:agentops-server:handoff_read": {
        "default": "allow"
      },
      "mcp:agentops-server:handoff.update": {
        "default": "allow"
      },
      "mcp:agentops-server:handoff_update": {
        "default": "allow"
      },
      "mcp:agentops-server:handoff.normalize": {
        "default": "allow"
      },
      "mcp:agentops-server:handoff_normalize": {
        "default": "allow"
      },
      "mcp:agentops-server:session.log_append": {
        "default": "allow"
      },
      "mcp:agentops-server:session_log_append": {
        "default": "allow"
      },
      "mcp:agentops-server:session.capture_context": {
        "default": "allow"
      },
      "mcp:agentops-server:session_capture_context": {
        "default": "allow"
      },
      "mcp:agentops-server:session.checkpoint": {
        "default": "allow"
      },
      "mcp:agentops-server:session_checkpoint": {
        "default": "allow"
      },
      "mcp:agentops-server:session.diff_since_checkpoint": {
        "default": "allow"
      },
      "mcp:agentops-server:session_diff_since_checkpoint": {
        "default": "allow"
      },
      "mcp:agentops-server:repo.verify": {
        "default": "allow"
      },
      "mcp:agentops-server:repo_verify": {
        "default": "allow"
      },
      "mcp:agentops-server:repo.commit": {
        "default": "allow"
      },
      "mcp:agentops-server:repo_commit": {
        "default": "allow"
      },
      "mcp:agentops-server:repo.status_summary": {
        "default": "allow"
      },
      "mcp:agentops-server:repo_status_summary": {
        "default": "allow"
      },
      "mcp:agentops-server:repo.commit_message_suggest": {
        "default": "allow"
      },
      "mcp:agentops-server:repo_commit_message_suggest": {
        "default": "allow"
      },
      "mcp:agentops-server:tests.suggest": {
        "default": "allow"
      },
      "mcp:agentops-server:tests_suggest": {
        "default": "allow"
      },
      "mcp:agentops-server:tests.suggest_from_failures": {
        "default": "allow"
      },
      "mcp:agentops-server:tests_suggest_from_failures": {
        "default": "allow"
      },
      "mcp:agentops-server:commit_if_verified": {
        "default": "allow"
      },
      "mcp:agentops-server:log_append": {
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

MCP tools:
- `handoff.read` (`handoff_read`)
- `handoff.update` (`handoff_update`)
- `handoff.normalize` (`handoff_normalize`)
- `session.log_append` (`session_log_append`)
- `session.capture_context` (`session_capture_context`)
- `session.checkpoint` (`session_checkpoint`)
- `session.diff_since_checkpoint` (`session_diff_since_checkpoint`)
- `repo.verify` (`repo_verify`)
- `repo.commit` (`repo_commit`)
- `repo.status_summary` (`repo_status_summary`)
- `repo.commit_message_suggest` (`repo_commit_message_suggest`)
- `tests.suggest` (`tests_suggest`)
- `tests.suggest_from_failures` (`tests_suggest_from_failures`)
- Legacy: `handoff_update`, `commit_if_verified`, `log_append`

Usage notes:
- Call `tools/list` to enumerate tools. Example request: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- Call `tools/call` to invoke a tool. Example request: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"handoff.update","arguments":{"summary":"Wrap up MCP tools","decisions":"Added structured handoff updates","next_actions":"Add tests for handoff parsing"}}}`
- Successful responses include a `result`; failures include an `error` with `code` and `message`.

Then register the MCP server in Zed and grant tool permissions as you prefer.

## License
MIT
