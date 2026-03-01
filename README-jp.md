# Zed AgentOps

- クロスセッションの引き継ぎ（.agent/handoff.md）
- CI/CD 的ループ：編集 -> verify -> commit -> handoff 更新
- テスト生成をループに含める（エージェントがテスト追加し、verify）

※ 現時点では動作環境は macOS のみです。

## クイックスタート

```bash
zed-agentops-init project_name
```

## インストール

```
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

`zed-agentops-init.sh` を使ってディレクトリをスキャフォールドします（`.rules`、`.zed/`、`.agent`、`.zed/scripts/verify` に加え、`.agent/journal.jsonl`、`.agent/snapshot.json`、`.agent/checkpoint.json` を作成）。
ディレクトリを Zed で開き、Agent パネルを使ってください。
`.gitignore` にはエントリが自動追記されます。

## 主要ファイルの配置

- `.rules` : Zed Agent のコンテキストに自動注入されるプロジェクトルール
- `.zed/tasks.json` : 再利用可能なタスク（verify、git ヘルパー）
- `.zed/scripts/verify` : build/test/lint の単一エントリーポイント（必要に応じて拡張）
- `.agent/handoff.md` : クロスセッション引き継ぎ（ソース・オブ・トゥルース）
- `.agent/work-in-progress.json` : 軽量なタスク状態（フェーズ、タスク、直近のアクション、次のステップ）
- `.agent/journal.jsonl` : 追記専用のイベントログ
- `.agent/snapshot.json` : 状態スナップショット
- `.agent/checkpoint.json` : ロールフォワード開始位置
- `src/agentops_mcp_server/` : 任意の MCP サーバスキャフォールド（Python）

## MCP Server (Zed)

MCP サーバは `src/agentops_mcp_server/main.py` にあり、Zed と互換の最小 JSON-RPC 2.0 stdio プロトコルを提供します。stdin から 1 行 1 JSON を読み、stdout に JSON-RPC 応答を返します。対応メソッドは `initialize`、`initialized`、`tools/list`、`tools/call`、`shutdown`、`exit` です。



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

提供ツール（snake_case）:
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
- 互換: ドット区切り（例: `roll_forward.replay`）は snake_case にマップされます

使用メモ:
- `tools/list` でツール一覧を取得。例: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- `tools/call` でツールを呼び出し。例: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"journal_append","arguments":{"kind":"task.start","payload":{"title":"v0.1.0 ドキュメント確認"}}}}`
- 成功時は `result`、失敗時は `error`（`code` と `message`）が返ります。

あとは Zed に MCP サーバを登録し、必要な権限を付与してください。

## ライセンス
MIT
