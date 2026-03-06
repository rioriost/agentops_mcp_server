# 0.4.0 Rebuild Engine Flow (Event Log → Materialized State)

This document specifies the rebuild engine flow for reconstructing materialized transaction state from the canonical event log.

## 1. Purpose
- Recover a deterministic materialized state after interruption or integrity mismatch.
- Provide a single authoritative path for resume decisions.

## 2. Inputs
- Event log (append-only), ordered by `seq`.
- Optional last known `last_applied_seq` cursor (if present).
- Current schema version (`0.4.0`).

## 3. Outputs
- Materialized transaction state with:
  - `active_tx` (or none)
  - `last_applied_seq`
  - `integrity.state_hash`
  - `updated_at`
- Rebuild status (`ok` | `failed`) with a brief summary.

## 4. Rebuild Preconditions
- Event log is readable and ordered by `seq`.
- If the log contains gaps or corrupt records, truncate to last valid `seq`.

## 5. Core Algorithm (Deterministic)
1. **Initialize**
   - Set empty state with `schema_version = 0.4.0`.
   - Set `last_applied_seq = 0`.
2. **Select replay range**
   - If a cursor exists, replay from `1` to cursor.
   - Otherwise, replay entire log.
3. **Replay events in order**
   - For each event:
     - Validate envelope fields.
     - Apply to in-memory state via deterministic reducers.
     - Update `last_applied_seq = event.seq`.
4. **Compute integrity**
   - Compute `state_hash` from the resulting materialized state.
5. **Finalize**
   - Set `integrity.rebuilt_from_seq = last_applied_seq`.
   - Update `updated_at`.

## 6. Reducer Rules (Summary)
- `tx.begin`: create `active_tx` if none; set status `planned` or `in-progress`.
- `tx.step.enter`: update `phase`, `current_step`.
- `tx.file_intent.*`: add/update file intent state with monotonic transitions.
- `tx.verify.*`: set verify state, ensure ordering.
- `tx.commit.*`: set commit state, ensure ordering.
- `tx.end.*`: mark transaction terminal and clear `active_tx`.

## 7. Integrity Checks
- Reject events that violate lifecycle invariants.
- On violation:
  - Stop at last valid `seq`.
  - Emit rebuild failure summary (short).
  - Materialized state reflects last valid point only.

## 8. Resume Derivation
- After rebuild, select latest non-terminal `active_tx`.
- Derive `next_action` from:
  - status
  - `current_step` / `last_completed_step`
  - file intent states
  - verify/commit state
  - `last_applied_seq`

## 9. Failure Modes
- **Corrupt tail**: truncate to last valid `seq`, rebuild.
- **Schema mismatch**: fail fast with summary.
- **Invariant breach**: stop at last valid seq, mark rebuild failed.

## 10. Observability
- Emit rebuild events:
  - `tx.state.rebuild.start` with `from_seq`
  - `tx.state.rebuild.done` with `to_seq` + `state_hash`
  - `tx.state.rebuild.fail` with short summary

## 11. Notes
- Rebuild must be idempotent and deterministic for the same event sequence.
- The event log is the source of truth; materialized state is derived only.