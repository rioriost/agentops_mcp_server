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

以下は空ファイルが原因とは思われないが、実装に問題があると思われる。

Error 5:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "p1-t1",
  "ticket_id": "p1-t1",
  "event_type": "tx.verify.pass",
  "phase": "in-progress",
  "step_id": "p1-t1",
  "actor": {
    "tool": "assistant"
  },
  "session_id": "default",
  "payload": {
    "ok": true
  }
}
put:
verify result requires verify.start

Error 6:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "p1-t1",
  "ticket_id": "p1-t1",
  "event_type": "tx.file_intent.update",
  "phase": "in-progress",
  "step_id": "p1-t1",
  "actor": {
    "tool": "assistant"
  },
  "session_id": "default",
  "payload": {
    "path": "docs/v0.4.5/plan.md",
    "state": "verified"
  }
}
Output:
file intent verified requires verify.pass

Error 7:
Run MCP tool `ops_start_task`
Raw Input:
{
  "title": "p1-t1 Regenerate 0.4.5 plan from draft",
  "task_id": "p1-t1",
  "session_id": "default",
  "agent_id": null,
  "status": "in-progress",
  "truncate_limit": 2000
}
Output:
tx.begin required before other events

Error 8:
Run MCP tool `ops_start_task`
Raw Input:
{
  "title": "p1-t1 Regenerate 0.4.5 plan from draft",
  "task_id": "p1-t1",
  "session_id": "default",
  "agent_id": null,
  "status": "in-progress",
  "truncate_limit": 2000
}
Output:
active transaction already in progress

Error 9:
Get current time
Raw Input:
{
  "timezone": "UTC"
}
Output:
Failed to parse tool input: unknown variant `UTC`, expected `utc` or `local

Error 10:
Run MCP tool `tx_event_append`
Raw Input:
{
  "tx_id": "p1-t1",
  "ticket_id": "p1-t1",
  "event_type": "tx.file_intent.update",
  "phase": "in-progress",
  "step_id": "p1-t1",
  "session_id": "default",
  "actor": {
    "tool": "assistant"
  },
  "payload": {
    "path": "docs/v0.4.5/plan.md",
    "state": "applied"
  }
}
Output:
file intent missing for path

Error 11:
Run MCP tool `tx_state_save`
Raw Input:
{
  "state": {
    "schema_version": "0.4.0",
    "active_tx": {
      "tx_id": "p1-t1",
      "ticket_id": "p1-t1",
      "status": "in-progress",
      "phase": "in-progress",
      "current_step": "p1-t1",
      "last_completed_step": "",
      "next_action": "tx.verify.pass",
      "semantic_summary": "Verification started for regenerated 0.4.5 plan/tickets.",
      "user_intent": null,
      "verify_state": {
        "status": "in-progress",
        "last_result": null
      },
      "commit_state": {
        "status": "not_started",
        "last_result": null
      },
      "file_intents": [
        {
          "path": "docs/v0.4.5/plan.md",
          "operation": "update",
          "purpose": "Regenerate 0.4.5 plan from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/tickets_list.json",
          "operation": "update",
          "purpose": "Regenerate tickets list from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p1-t1.json",
          "operation": "update",
          "purpose": "Regenerate p1-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p1-t2.json",
          "operation": "update",
          "purpose": "Regenerate p1-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p2-t1.json",
          "operation": "update",
          "purpose": "Regenerate p2-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p2-t2.json",
          "operation": "update",
          "purpose": "Regenerate p2-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p2-t3.json",
          "operation": "update",
          "purpose": "Regenerate p2-t3 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p3-t1.json",
          "operation": "update",
          "purpose": "Regenerate p3-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p3-t2.json",
          "operation": "update",
          "purpose": "Regenerate p3-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p4-t1.json",
          "operation": "update",
          "purpose": "Regenerate p4-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        },
        {
          "path": "docs/v0.4.5/p4-t2.json",
          "operation": "update",
          "purpose": "Regenerate p4-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "applied"
        }
      ],
      "_last_event_seq": 93,
      "_terminal": false
    },
    "last_applied_seq": 93,
    "integrity": {
      "state_hash": "",
      "rebuilt_from_seq": 68
    },
    "updated_at": "2026-03-08T01:03:52.310683+00:00",
    "rebuild_warning": null,
    "rebuild_invalid_event": null,
    "rebuild_invalid_seq": null
  }
}
Output:
active_tx.verify_state.status is invalid

Error 12:
Run MCP tool `tx_state_save`
Raw Input:
{
  "state": {
    "schema_version": "0.4.0",
    "active_tx": {
      "tx_id": "p1-t1",
      "ticket_id": "p1-t1",
      "status": "in-progress",
      "phase": "checking",
      "current_step": "p1-t1",
      "last_completed_step": "",
      "next_action": "check acceptance criteria",
      "semantic_summary": "Verification passed; file intents marked verified; ready to check acceptance criteria.",
      "user_intent": null,
      "verify_state": {
        "status": "passed",
        "last_result": {
          "ok": true
        }
      },
      "commit_state": {
        "status": "not_started",
        "last_result": null
      },
      "file_intents": [
        {
          "path": "docs/v0.4.5/plan.md",
          "operation": "update",
          "purpose": "Regenerate 0.4.5 plan from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/tickets_list.json",
          "operation": "update",
          "purpose": "Regenerate tickets list from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p1-t1.json",
          "operation": "update",
          "purpose": "Regenerate p1-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p1-t2.json",
          "operation": "update",
          "purpose": "Regenerate p1-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p2-t1.json",
          "operation": "update",
          "purpose": "Regenerate p2-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p2-t2.json",
          "operation": "update",
          "purpose": "Regenerate p2-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p2-t3.json",
          "operation": "update",
          "purpose": "Regenerate p2-t3 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p3-t1.json",
          "operation": "update",
          "purpose": "Regenerate p3-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p3-t2.json",
          "operation": "update",
          "purpose": "Regenerate p3-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p4-t1.json",
          "operation": "update",
          "purpose": "Regenerate p4-t1 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        },
        {
          "path": "docs/v0.4.5/p4-t2.json",
          "operation": "update",
          "purpose": "Regenerate p4-t2 ticket from updated draft",
          "planned_step": "p1-t1",
          "state": "verified"
        }
      ],
      "_last_event_seq": 105,
      "_terminal": false
    },
    "last_applied_seq": 105,
    "integrity": {
      "state_hash": "",
      "rebuilt_from_seq": 68
    },
    "updated_at": "2026-03-08T01:03:52.310683+00:00",
    "rebuild_warning": null,
    "rebuild_invalid_event": null,
    "rebuild_invalid_seq": null
  }
}
Output:
active_tx.phase must match status

Error 13:
Run MCP tool `commit_if_verified`
Raw Input:
{
  "message": "docs: refresh 0.4.5 draft plan and tickets",
  "timeout_sec": 120,
  "truncate_limit": 2000
}
Output:
verify.start not recorded; tx.begin required before verify results



- tx_event_log.jsonlが空の場合は、zed-agentops-init.shによる初期化状態として扱うべき。

## Goal
- tx_event_log.jsonlが空であっても、エラーが発生しない。
- トランザクション制御が、.rulesとMCPサーバの間で整合しており、エラーが発生しない。

## Acceptance criteria
- カバレッジ90%以上
