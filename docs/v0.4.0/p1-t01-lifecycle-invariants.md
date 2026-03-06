# 0.4.0 Transaction Lifecycle Invariants

This document defines the invariants that must hold for every ticket transaction in 0.4.0. These invariants are normative and must be enforced by the runtime and by recovery logic.

## 1. Transaction identity and uniqueness
1. Each transaction has a globally unique `tx_id`.
2. Each transaction is associated with exactly one `ticket_id`.
3. At most one **active** (non-terminal) transaction exists per worker/session context.

## 2. Event ordering and boundaries
1. A transaction must begin with exactly one `tx.begin` event.
2. No transaction events may appear before `tx.begin` for that `tx_id`.
3. A transaction must end with exactly one terminal event:
   - `tx.end.done`, or
   - `tx.end.blocked`
4. No events may appear after a terminal event for the same `tx_id`.

## 3. Phase and step coherence
1. `tx.step.enter` events must reference a valid `phase` and `step_id`.
2. A `tx.step.enter` event must not repeat the same `(phase, step_id)` without a preceding step completion or explicit rollback marker (if rollback is introduced later).
3. `current_step` in materialized state must equal the latest `tx.step.enter` event for the active transaction.
4. `last_completed_step` must never be ahead of `current_step` in the event stream order.

## 4. File intent invariants
1. A file intent must be registered (`tx.file_intent.add`) **before** any file mutation for that file path.
2. All file mutation events must reference an existing file intent entry.
3. File intent state transitions must be monotonic:
   - `planned` → `started` → `applied` → `verified`
4. `tx.file_intent.update` may only target an existing intent and must not skip states.
5. A file intent may be marked `verified` only after verification has started for the transaction.

## 5. Verification invariants
1. `tx.verify.start` may only occur after at least one `tx.step.enter` during `in-progress`.
2. `tx.verify.pass` and `tx.verify.fail` are mutually exclusive and must follow `tx.verify.start`.
3. If `tx.verify.fail` occurs, transaction status must remain `checking` or revert to `in-progress` per runtime policy, but must not advance to `committed`.

## 6. Commit invariants
1. `tx.commit.start` may only occur after `tx.verify.pass`.
2. `tx.commit.done` and `tx.commit.fail` are mutually exclusive and must follow `tx.commit.start`.
3. A transaction must not reach terminal `tx.end.done` unless `tx.commit.done` occurred.

## 7. Status progression invariants
1. Valid status progression is:
   - `planned` → `in-progress` → `checking` → `verified` → `committed` → `done`
2. `blocked` is a terminal status and must only be set by `tx.end.blocked`.
3. Status must never regress except when explicitly defined by verification failure policy (e.g., `checking` → `in-progress`), and such regression must be recorded by an event.

## 8. Resume and recovery invariants
1. Resume must target the latest non-terminal transaction by event sequence order.
2. `next_action` must be derivable solely from:
   - transaction status,
   - step markers,
   - file intent states,
   - verify/commit states,
   - and the last applied sequence.
3. If materialized state integrity fails, state must be rebuilt from event log to the last durable sequence.

## 9. Integrity and determinism invariants
1. Materialized state must be consistent with event log up to `last_applied_seq`.
2. Rebuilding from event log up to `last_applied_seq` must yield an equivalent materialized state (`state_hash` match).
3. On mismatch, materialized state is discarded in favor of rebuild.

## 10. Terminal transaction invariants
1. A terminal transaction must not be resumed.
2. A new transaction may only begin after the current active transaction is terminal.

---

These invariants are intended to keep the 0.4.0 transaction model deterministic, verifiable, and robust under interruption.