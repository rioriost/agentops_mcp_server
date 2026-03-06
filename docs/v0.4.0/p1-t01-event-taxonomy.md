# 0.4.0 Transaction Event Taxonomy

This document defines the canonical event taxonomy for 0.4.0 transaction-aware ticket execution. It is the authoritative list of event types and required payload fields.

## 1. Goals

- Make transaction execution resumable and deterministic.
- Ensure every state transition is logged before derived state changes.
- Provide enough semantics to rebuild materialized state and `next_action`.

## 2. Event Record Envelope (Required Fields)

Every event record MUST include:

- `seq` (monotonic sequence number)
- `ts` (RFC3339 timestamp)
- `tx_id`
- `ticket_id`
- `event_type` (from the taxonomy below)
- `phase` (logical phase of the ticket)
- `step_id` (identifier for current step)
- `payload` (event-specific payload, may be empty)
- `actor`
- `session_id`

## 3. Canonical Event Types

All event types are namespaced by `tx.*` and must be emitted in the order rules defined in the lifecycle invariants.

### 3.1 Transaction Lifecycle Boundaries

- `tx.begin`
  - Emitted when a ticket becomes the active transaction.
  - Required payload:
    - `plan_version`
    - `ticket_title`

- `tx.end.done`
  - Emitted when a transaction completes successfully.
  - Required payload:
    - `final_status` (must be `done`)

- `tx.end.blocked`
  - Emitted when a transaction is ended as blocked.
  - Required payload:
    - `final_status` (must be `blocked`)
    - `reason`

### 3.2 Step Transitions

- `tx.step.enter`
  - Emitted at the start of a logical step in the ticket.
  - Required payload:
    - `step_name`

- `tx.step.exit`
  - Emitted after a logical step completes.
  - Required payload:
    - `step_name`
    - `result` (`ok` | `skipped` | `failed`)

### 3.3 File Intent Lifecycle

File intents are required before any file mutation.

- `tx.file_intent.add`
  - Register a new file intent.
  - Required payload:
    - `path`
    - `operation` (`create` | `edit` | `overwrite` | `delete` | `move` | `copy`)
    - `purpose` (human-readable intent)
    - `planned_step`

- `tx.file_intent.update`
  - Update intent metadata (e.g., operation refinement).
  - Required payload:
    - `path`
    - `operation` (updated)
    - `purpose` (updated, if changed)

- `tx.file_intent.start`
  - Emitted immediately before first mutation for the file.
  - Required payload:
    - `path`
    - `operation`

- `tx.file_intent.apply`
  - Emitted after mutation is applied.
  - Required payload:
    - `path`
    - `operation`
    - `result` (`ok` | `failed`)
    - `details` (optional error summary if failed)

- `tx.file_intent.verify`
  - Emitted when file-specific verification completes (optional).
  - Required payload:
    - `path`
    - `result` (`ok` | `failed`)

- `tx.file_intent.complete`
  - Emitted when the intent is fully satisfied.
  - Required payload:
    - `path`
    - `final_state` (`verified` | `applied`)

### 3.4 Verification Milestones

- `tx.verify.start`
  - Emitted before running `${VERIFY_REL}`.
  - Required payload:
    - `command`

- `tx.verify.pass`
  - Emitted when verification succeeds.
  - Required payload:
    - `duration_ms`

- `tx.verify.fail`
  - Emitted when verification fails.
  - Required payload:
    - `duration_ms`
    - `summary` (short error synopsis)

### 3.5 Commit Milestones

- `tx.commit.start`
  - Emitted before commit attempt.
  - Required payload:
    - `message`
    - `changed_files` (array of paths or a summary string)

- `tx.commit.done`
  - Emitted after commit succeeds.
  - Required payload:
    - `sha`
    - `message`

- `tx.commit.fail`
  - Emitted after commit fails.
  - Required payload:
    - `summary` (short error synopsis)

### 3.6 Persistence and Recovery Events

- `tx.state.persist`
  - Emitted after materialized state is written with cursor.
  - Required payload:
    - `last_applied_seq`
    - `state_hash`

- `tx.state.rebuild.start`
  - Emitted when rebuilding state from log begins.
  - Required payload:
    - `from_seq`

- `tx.state.rebuild.done`
  - Emitted when rebuild completes.
  - Required payload:
    - `to_seq`
    - `state_hash`

- `tx.state.rebuild.fail`
  - Emitted when rebuild fails.
  - Required payload:
    - `summary`

## 4. Ordering Rules (Summary)

- `tx.begin` MUST exist before any `tx.file_intent.*`.
- `tx.file_intent.add` MUST precede `tx.file_intent.start/apply`.
- `tx.verify.start` MUST precede `tx.verify.pass/fail`.
- `tx.commit.start` MUST precede `tx.commit.done/fail`.
- `tx.end.*` MUST be the last event for a transaction.

## 5. Notes

- This taxonomy is canonical for 0.4.0. No aliases or alternative names are allowed.
- Additional event types must be proposed in a future plan update before use.