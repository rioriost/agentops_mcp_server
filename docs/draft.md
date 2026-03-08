# Draft for 0.4.10: resume-safety fixes

## Background
- `initial-dot-agent/` contains copied `.agent/` artifacts from another project for investigation purposes only. The files were not produced by this repository.
- The copied artifacts include:
  - `tx_event_log.jsonl`
  - `tx_state.json`
  - `handoff.json`
  - `errors.jsonl`
- The copied `errors.jsonl` shows failures such as:

{"ts": "2026-03-08T06:51:38.325330+00:00", "tool_name": "ops_start_task", "tool_input": {"title": "Implement p1-t2 configuration and logging foundation", "task_id": "p1-t2", "session_id": "default", "agent_id": "gpt-5.4", "status": "in-progress", "truncate_limit": 4000}, "tool_output": {"error": "tx_id does not match active transaction"}}
{"ts": "2026-03-08T06:51:38.325817+00:00", "tool_name": "ops_update_task", "tool_input": {"status": "in-progress", "note": "Starting p1-t2 by strengthening settings schema, environment-variable documentation, config-file loading, and logging safety/debug behavior on top of the initial skeleton.", "task_id": "p1-t2", "session_id": "default", "agent_id": "gpt-5.4", "user_intent": "Proceed with implementation from the next executable ticket.", "truncate_limit": 4000}, "tool_output": {"error": "tx_id does not match active transaction"}}

- The copied `tx_state.json` shows that `p1-t1` was still the active transaction, with `status=checking` and `next_action=tx.verify.start`.
- This indicates a realistic failure mode:
  1. an active transaction already exists,
  2. resume logic or operator guidance selects the next planned ticket instead of resuming the active one,
  3. runtime correctly rejects the new task start with `tx_id does not match active transaction`.

## Problem
The current runtime guard is correct, but the system does not make the recovery path clear enough before a new task start is attempted.

In particular:
- resume guidance does not strongly emphasize that an existing active transaction must be resumed first,
- error messages do not clearly explain which transaction is active and what the caller should do next,
- resume-time guidance is not explicit enough to steer callers back to the active transaction before they try to start the next ticket.

## Goal
- Prevent agents and operators from attempting to start a new ticket while another transaction is still active.
- Make resume behavior explicit, actionable, and safe.
- Keep resume behavior focused on the active transaction and make the safe recovery path obvious.

## Proposed changes
- Strengthen resume output so it clearly reports:
  - the active ticket,
  - the active status,
  - the required next action,
  - whether starting a new ticket is allowed.
- Improve task-start and task-update mismatch errors so they include:
  - the active transaction id,
  - the requested task id,
  - the required recovery action.
- Update `.rules` guidance so active transaction resumption is explicitly prioritized over choosing the next executable ticket.

## Non-goals
- Relaxing transaction-ordering invariants.
- Allowing automatic continuation into a new ticket when an active transaction already exists.
- Introducing foreign-state detection features that are not needed for normal operation.

## Goal
- Resume safety is improved without weakening transaction correctness.

## Acceptance criteria
- `ops_resume_brief` clearly indicates when an active transaction must be resumed and when a new ticket must not be started.
- Starting or updating a task with a mismatched `task_id` produces an actionable error message that identifies both the active and requested transaction ids.
- `.rules` explicitly states that an active transaction must be resumed before selecting the next executable ticket.
- Existing transaction guards remain strict.
- Coverage remains 90% or higher.