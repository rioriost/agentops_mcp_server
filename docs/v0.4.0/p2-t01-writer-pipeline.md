# 0.4.0 Writer Pipeline: Ordering and Atomicity Rules

This document specifies the canonical writer pipeline for the 0.4.0 transaction model. The pipeline defines the **required ordering** and **atomicity expectations** for durable state in the event log and materialized transaction state.

## 1. Purpose

- Guarantee deterministic resume and replay.
- Minimize torn-state ambiguity after interruption.
- Ensure event history is the canonical source of truth.

## 2. Canonical Pipeline (Strict Order)

For any ticket progress action that mutates or advances state:

1. **Append event(s) to the transaction event log.**
   - This is the canonical history.
   - Events must be appended in the order defined by lifecycle invariants.

2. **Apply events to the materialized transaction state in memory.**
   - Derive `status`, `current_step`, `file_intents`, `verify_state`, `commit_state`, and `next_action`.

3. **Persist the materialized transaction state with cursor.**
   - Write the state document **atomically** with its `last_applied_seq`.
   - Emit `tx.state.persist` after successful write with `state_hash`.

4. **Optionally regenerate derived views** (e.g., handoff).
   - Derived views are convenience outputs and not canonical.

## 3. Atomicity Requirements

- **Event log append is atomic** per event record.
- **State + cursor persist is atomic** as a single write unit.
- If step 3 fails, the system must **not** claim the new `last_applied_seq`.

## 4. Failure Scenarios and Expected Recovery

### 4.1 Failure after event append, before state persist
- Event log contains the latest canonical intent.
- Materialized state may be stale.
- **Recovery:** rebuild state from log up to highest durable sequence.

### 4.2 Failure during state persist
- State may be partially written or corrupt.
- **Recovery:** discard invalid state and rebuild from log.

### 4.3 Failure after state persist, before derived view regeneration
- Canonical state is valid.
- **Recovery:** regenerate derived views from state on next start.

## 5. Ordering Constraints (Summary)

- **Log first, state second, derived last.**
- `tx.begin` must precede all mutation or file intent events.
- `tx.file_intent.add` must precede any file mutation.
- `tx.verify.start` must precede `tx.verify.pass/fail`.
- `tx.commit.start` must precede `tx.commit.done/fail`.
- `tx.end.*` must be the final event for a transaction.

## 6. Cursor and Sequence Policy

- `last_applied_seq` is the **single source** of "how far state is materialized."
- Any state without a valid cursor is **invalid** and must be rebuilt.

## 7. Implementation Notes

- The runtime must treat **event log + state** as the canonical system.
- Derived artifacts (handoff) must never be consulted for resume decisions.
- Integrity checks must compare state hash to a rebuild result at `last_applied_seq`.

---

This pipeline is required for 0.4.0. Deviations must be justified in a future plan update and will otherwise be considered violations of the transaction model.