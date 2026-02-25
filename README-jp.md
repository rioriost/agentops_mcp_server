# Zed AgentOps

- クロスセッションの引き継ぎ（.agent/handoff.md）
- CI/CD 的ループ：編集 -> verify -> commit -> handoff 更新
- テスト生成をループに含める（エージェントがテスト追加し、verify）

## クイックスタート

```bash
zed-agentops-init project_name
```

## インストール

```
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

`zed-agentops-init.sh` を使ってディレクトリをスキャフォールドします（`.rules`、`.zed/`、`.agent`、`.zed/scripts/verify` を作成）。
ディレクトリを Zed で開き、Agent パネルを使ってください。
`.gitignore` には `.zed/` と `.agent/` などのエントリが自動追記されます。

## 主要ファイルの配置

- `.rules` : Zed Agent のコンテキストに自動注入されるプロジェクトルール
- `.zed/tasks.json` : 再利用可能なタスク（verify、git ヘルパー）
- `.zed/scripts/verify` : build/test/lint の単一エントリーポイント（必要に応じて拡張）
- `.agent/handoff.md` : クロスセッション引き継ぎ（ソース・オブ・トゥルース）
- `.agent/session-log.jsonl` : オプションのイベントログ（追記のみ）
- `.agent/checkpoints/` : diff チェックポイント（json スナップショット）
- `src/agentops_mcp_server/` : 任意の MCP サーバスキャフォールド（Python）

## MCP Server (Zed)

MCP サーバは `src/agentops_mcp_server/main.py` にあり、Zed と互換の最小 JSON-RPC 2.0 stdio プロトコルを提供します。stdin から 1 行 1 JSON を読み、stdout に JSON-RPC 応答を返します。対応メソッドは `initialize`、`initialized`、`tools/list`、`tools/call`、`shutdown`、`exit` です。

起動方法:
- `uv run agentops_mcp_server`

Zed (MCP):
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

提供ツール（例）:
- `handoff.read` / `handoff_read`
- `handoff.update` / `handoff_update`
- `handoff.normalize` / `handoff_normalize`
- `session.log_append` / `session_log_append`
- `session.capture_context` / `session_capture_context`
- `session.checkpoint` / `session_checkpoint`
- `session.diff_since_checkpoint` / `session_diff_since_checkpoint`
- `repo.verify` / `repo_verify`
- `repo.commit` / `repo_commit`
- `repo.status_summary` / `repo_status_summary`
- `repo.commit_message_suggest` / `repo_commit_message_suggest`
- `tests.suggest` / `tests_suggest`
- `tests.suggest_from_failures` / `tests_suggest_from_failures`
- 互換ツール: `handoff_update`, `commit_if_verified`, `log_append`

使用メモ:
- `tools/list` でツール一覧を取得。例: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- `tools/call` でツールを呼び出し。例: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"handoff.read","arguments":{}}}`
- 成功時は `result`、失敗時は `error`（`code` と `message`）が返ります。

あとは Zed に MCP サーバを登録し、必要な権限を付与してください。

## ライセンス
MIT
