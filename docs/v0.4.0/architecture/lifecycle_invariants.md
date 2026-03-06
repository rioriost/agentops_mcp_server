# Lifecycle Invariants (0.4.0)

This document defines the transaction lifecycle invariants for deterministic resume and replay.

## Terminology
- **Transaction (tx)**: The unit of work for a ticket.
- **Event log**: Append-only log of tx events.
- **Materialized state**: Latest tx state derived from the event log.
- **File intent**: Explicit metadata describing a file mutation before it occurs.

## Invariants

### 1) Single active transaction
- Exactly one **active, non-terminal** transaction exists per execution context.
- A transaction is **active** if its latest terminal event (`tx.end.*`) has not been observed.

### 2) Transaction boundaries
- `tx.begin` **must** be the first event for a transaction id.
- `tx.end.done` or `tx.end.blocked` **must** be the last event for a transaction id.
- No events are valid for a transaction **after** a terminal event.

### 3) Step ordering
- `tx.step.enter` **must** reference an existing `tx_id` and `ticket_id`.
- For a given step, only one active `current_step` is allowed at a time.
- `last_completed_step` can only advance forward; it must never regress.

### 4) File intent before mutation
- A `tx.file_intent.add` event **must** exist **before** any mutation event for that file.
- All mutation-related events must reference an existing intent entry.
- Intent state transitions must be monotonic:
  - `planned → started → applied → verified`
- An intent cannot be marked `verified` before `verify.pass`.

### 5) Verification and commit ordering
- `tx.verify.start` must occur **after** all mutation events for the step.
- `tx.verify.pass|fail` must follow `tx.verify.start`.
- `tx.commit.start` must occur **after** `tx.verify.pass`.
- `tx.commit.done|fail` must follow `tx.commit.start`.

### 6) Event completeness
Every transaction event must include these fields:
- `tx_id`, `ticket_id`, `event_type`, `phase`, `step_id`, `actor`, `session_id`

### 7) Deterministic resume selection
- Resume **must** select the latest **non-terminal** transaction.
- If multiple non-terminal transactions appear due to corruption, prefer the one with the highest valid `seq`, then rebuild.

### 8) Torn-state precedence
- Event log is the canonical source.
- Materialized state is trusted only if integrity checks pass.
- On mismatch, rebuild materialized state from the event log up to the last durable sequence.

### 9) Replay idempotency
- Reapplying the same sequence of events produces the same materialized state.
- Duplicate event ids are ignored and recorded as `dropped_events`.

## Validation Rules
- Reject event records missing any required fields.
- Reject mutation events without a prior file intent.
- Reject terminal events if `tx.begin` is missing.
- Reject multiple terminal events for the same transaction.

## Notes
These invariants are mandatory for deterministic resume and must be enforced in both write-time validation and replay-time reconstruction.