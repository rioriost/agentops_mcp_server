# Draft for 0.4.5: bug fixes

## Background
- tx_event_log.jsonlが存在しない状態からジョブを開始した際にエラーが発生する。tx_event_log.jsonlはtouchしたのみで空ファイル。
Error 1:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "tx-p1-t1-001",
  "ticket_id": "p1-t1",
  "event_type": "tx.begin",
  "phase": "work",
  "step_id": "p1-t1",
  "session_id": ""
}
Output:
Missing required argument(s): actor, payload

Error 2:
Run MCP tool `tx_state_save`
Raw Input:
{}
Output:
Missing required argument(s): state

Error 3:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "tx-p1-t1-001",
  "ticket_id": "p1-t1",
  "event_type": "tx.begin",
  "phase": "work",
  "step_id": "p1-t1",
  "session_id": "",
  "actor": "assistant",
  "payload": {
    "note": "Begin p1-t1"
  }
}
Output:
session_id is required

Error 4:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "p1-t1",
  "ticket_id": "p1-t1",
  "event_type": "tx.begin",
  "phase": "work",
  "step_id": "p1-t1",
  "session_id": "default",
  "actor": "assistant",
  "payload": {
    "note": "begin p1-t1"
  }
}
Output:
actor is required

- tx_event_log.jsonlが空の場合は、zed-agentops-init.shによる初期化状態として扱うべき。

## Goal
- tx_event_log.jsonlが空であっても、エラーが発生しない。

## Acceptance criteria
- カバレッジ90%以上
