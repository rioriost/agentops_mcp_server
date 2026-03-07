# Draft for 0.4.4: bug fixes

## Background
- 0.4.3を実際に使うと、バグが発見された。原因は複数あると推測される。
  - src/以下のPythonの実装（MCPサーバのtools）と、.rulesが整合していない。引数が不足する。
  - トランザクションとして管理するために、より厳密な.rulesが必要。toolを呼び出す順番が守られてない？
- 以下はエラーメッセージ。
1. commit_if_verified:
Raw Input:
```json
{
  "message": "docs: replan for release_brew copy",
  "timeout_sec": 120,
  "truncate_limit": 1000
}
```
Output:
```quote
verify result requires verify.start
```

2. ops_start_task
Raw Input:
```json
{
  "title": "p1-t2: Create release_brew.py copy with release/checkdep entrypoint",
  "task_id": "p1-t2",
  "session_id": "local",
  "agent_id": "assistant",
  "status": "in-progress",
  "truncate_limit": 1000
}
```
Output:
```quote
active transaction already in progress
```

3. ops_update_task
```json
{
  "status": "in-progress",
  "note": "Start p1-t2: copy dependency_update.py to release_brew.py and rewrite entrypoint for release/checkdep.",
  "task_id": "p1-t2",
  "session_id": "local",
  "agent_id": "assistant",
  "user_intent": null,
  "truncate_limit": 1000
}
```
Output:
```quote
tx_id does not match active transaction
```

```quote
失敗原因は、`agentops_mcp_server/.agent/tx_event_log.jsonl` に不整合なイベント（例: `tx.commit.start` が `tx.begin`/`verify.start` なしで記録）が含まれており、`tx_state` の再構築が `seq 18` で止まってしまうためです。これにより `tx.begin` の後続イベントが「active transactionとtx_idが合わない」と判定されます。
```

- 原因を検討し、修正案を作成後、修正を実行する。

## Goal
- エラーが出ない。

## Acceptance criteria
- カバレッジ90%以上
