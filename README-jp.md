# Zed AgentOps

- CI/CD 的ループ：編集 -> verify -> commit
- テスト生成をループに含める（エージェントがテスト追加し、verify）

※ 現時点では動作環境は macOS のみです。

## クイックスタート

```bash
zed-agentops-init project_name
zed-agentops-init --update existing_project
```

`--update` を使うと既存の AgentOps 管理ディレクトリを移行できます（legacy ファイル削除、`.agent` 状態ファイル作成、`.rules` 更新）。

## インストール

```
brew tap rioriost/agentops_mcp_server
brew install agentops_mcp_server
```

`zed-agentops-init.sh` を使ってディレクトリをスキャフォールドします（`.rules`、`.zed/`、`.agent`、`.zed/scripts/verify` に加え、`.agent/journal.jsonl`、`.agent/snapshot.json`、`.agent/checkpoint.json` を作成）。
ディレクトリを Zed で開き、Agent パネルを使ってください。
リリース向けのカバレッジ計測は `.zed/scripts/verify-release`（`pytest-cov` が必要）を使ってください。
`.gitignore` にはエントリが自動追記されます。

## ワークフローのヒント

- セッション終了前／コンテキストが厳しいとき:
  - `ops_compact_context` を実行（`include_diff=false` 推奨、`max_chars` は任意）
  - `ops_handoff_export` は `.agent/handoff.json` に書き出し（`path` 指定時は `.agent/` 配下の相対パスとして扱う）
- すぐ再開する場合は `ops_resume_brief` を実行
- タスクの進行記録: `ops_start_task` / `ops_update_task` / `ops_end_task`
- 状態スナップショットと要約: `ops_capture_state` / `ops_task_summary` / `ops_observability_summary`
- トークン節約: フル diff より要約・diff stats を優先し、出力は短く保つ
- 全ての MCP ツールは `workspace_root` と `truncate_limit` を任意で受け付ける（`tools/list` で確認）

## .rulesについて（from v0.2.0）
zed-agentops-init は `.rules` を生成しますが、必要に応じて `docs/rules_short` か `docs/rules_long` も試してみてください。

## 主要ファイルの配置

- `.rules` : Zed Agent のコンテキストに自動注入されるプロジェクトルール
- `.zed/tasks.json` : 再利用可能なタスク（verify、git ヘルパー）
- `.zed/scripts/verify` : build/test/lint の単一エントリーポイント（必要に応じて拡張）
- `.zed/scripts/verify-release` : リリース向けのカバレッジ計測（pytest-cov）

- `.agent/journal.jsonl` : 追記専用のイベントログ
- `.agent/snapshot.json` : 状態スナップショット
- `.agent/checkpoint.json` : ロールフォワード開始位置
- `/opt/homebrew/bin/agentops_mcp_server` : Homebrew でインストールされる MCP サーババイナリ（macOS）

## MCP Server (Zed)

MCP サーバは Homebrew でインストールされるバイナリ（例: `/opt/homebrew/bin/agentops_mcp_server`）として提供され、Zed と互換の最小 JSON-RPC 2.0 stdio プロトコルを提供します。stdin から 1 行 1 JSON を読み、stdout に JSON-RPC 応答を返します。対応メソッドは `initialize`、`initialized`、`tools/list`、`tools/call`、`shutdown`、`exit` です。



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
- `ops_compact_context`
- `ops_handoff_export`
- `ops_resume_brief`
- `ops_start_task`
- `ops_update_task`
- `ops_end_task`
- `ops_capture_state`
- `ops_task_summary`
- `ops_observability_summary`
- 互換: ドット区切り（例: `roll_forward.replay`）は snake_case にマップされます

使用メモ:
- `tools/list` でツール一覧を取得。例: `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`
- `tools/call` でツールを呼び出し。例: `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"journal_append","arguments":{"kind":"task.start","payload":{"title":"v0.1.0 ドキュメント確認"}}}}`
- 成功時は `result`、失敗時は `error`（`code` と `message`）が返ります。

あとは Zed に MCP サーバを登録し、必要な権限を付与してください。

## ライセンス
MIT
