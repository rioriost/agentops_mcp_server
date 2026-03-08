# Draft for 0.4.8: bug fixes

## Background
- initial-dot-agent/に、zed-agentops-init.shを実行し、Zedでプロジェクトディレクトリを開いた直後の、journal.jsonl、tx_event_log.jsonl、tx_state.jsonを置きました。
- この状態から、AIエージェントを利用開始した場合、以下のエラーが出ます。

{"ts": "2026-03-08T05:34:11.179215+00:00", "tool_name": "ops_start_task", "tool_input": {"title": "Generate v0.0.1 plan and ticket files from docs/draft.md", "task_id": "plan-v0.0.1", "session_id": "mnemis-plan-session", "agent_id": "gpt-5.4", "status": "in-progress", "truncate_limit": 4000}, "tool_output": {"error": "tx.begin required before other events"}}
{"ts": "2026-03-08T05:34:11.180247+00:00", "tool_name": "ops_update_task", "tool_input": {"status": "in-progress", "note": "Starting planning flow from docs/draft.md per project rules. Resume brief indicates no active ticket; creating initial plan artifacts for versioned docs.", "task_id": "plan-v0.0.1", "session_id": "mnemis-plan-session", "agent_id": "gpt-5.4", "user_intent": "Start work following .rules using docs/draft.md as the planning source.", "truncate_limit": 4000}, "tool_output": {"error": "tx.begin required before other events"}}
{"ts": "2026-03-08T05:35:39.704654+00:00", "tool_name": "ops_capture_state", "tool_input": {"session_id": "mnemis-plan-session", "truncate_limit": 4000}, "tool_output": {"error": "active_tx.next_action is required"}}
{"ts": "2026-03-08T05:35:39.705625+00:00", "tool_name": "ops_handoff_export", "tool_input": {"truncate_limit": 4000}, "tool_output": {"error": "active_tx.next_action is required"}}

- 原因を調査し、.rules、zed-agentops-init.sh、src/以下のPythonコードを修正する必要があります。

## Goal
- 初期状態から作業を開始しても、エラーが発生しないこと。

## Acceptance criteria
- カバレッジ90%以上
