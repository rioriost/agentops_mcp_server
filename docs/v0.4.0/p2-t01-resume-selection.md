# 0.4.0 Resume Selection Logic (Active Transaction)

This document defines how the runtime chooses which transaction to resume and how `next_action` is derived in 0.4.0. It assumes the canonical event log and materialized transaction state described in the plan.

## 1. Inputs
- Materialized transaction state (if present).
- Event log (append-only).
- Cursor / `last_applied_seq` (from state).
- Integrity metadata (state hash, rebuild provenance).

## 2. Selection Preconditions
1. Load materialized state.
2. Validate integrity:
   - `state_hash` matches recomputation (if supported).
   - `last_applied_seq` is <= highest durable log sequence.
3. If integrity fails or state is missing, rebuild state from log (see rebuild spec) and re-validate.

## 3. Active Transaction Selection
1. Identify the latest non-terminal transaction by event sequence order.
   - Non-terminal = last event type is **not** `tx.end.done` or `tx.end.blocked`.
2. If no non-terminal transaction exists:
   - Select the next planned ticket (per scheduler policy).
   - Emit `tx.begin` for the new transaction.
3. If multiple non-terminal transactions exist (should not happen):
   - Choose the one with the highest `seq`.
   - Emit a diagnostic event indicating invariant violation.

## 4. Determining `next_action`
Given the selected active transaction, derive `next_action` deterministically:

### 4.1 Status-driven decisions
- `planned`:
  - `next_action`: begin transaction and enter first step.
- `in-progress`:
  - `next_action`: continue current step or register file intents for pending mutations.
- `checking`:
  - If `tx.verify.start` not present: run verification.
  - If `tx.verify.fail` present: return to remediation step.
- `verified`:
  - `next_action`: commit changes.
- `committed`:
  - `next_action`: emit `tx.end.done`.
- `blocked`:
  - `next_action`: none (terminal).

### 4.2 File intent constraints
- If any file intent is `planned` but the next step requires mutation:
  - `next_action`: emit `tx.file_intent.start` for that intent before mutation.
- If any file intent is `started` but not `applied`:
  - `next_action`: re-apply mutation or re-validate mutation result.
- If any file intent is `applied` but not `verified`:
  - `next_action`: run verification or mark `verified` if global verification already passed.

### 4.3 Verification and commit gates
- Verification is required before any commit attempt.
- Commit is required before `tx.end.done`.
- `next_action` must never skip required gates.

## 5. Resume Event Emission
On resume, the runtime MUST emit:
- `tx.step.enter` for the step being resumed.
- If a rebuild occurred:
  - `tx.state.rebuild.start` and `tx.state.rebuild.done` events (per taxonomy).

## 6. Determinism Guarantees
- Given the same event log and `last_applied_seq`, the selection of active transaction and `next_action` MUST be identical.
- Materialized state is authoritative only if integrity is valid; otherwise, rebuild is the sole source of truth.

## 7. Failure Handling
- If the log tail is corrupted or contains invalid records:
  - Truncate to the last valid sequence.
  - Rebuild state and resume from the last valid boundary.
- If required data for `next_action` is missing:
  - Emit a blocking event and set status to `blocked`.

---

This logic is canonical for 0.4.0 and must be applied consistently across all resumption paths.