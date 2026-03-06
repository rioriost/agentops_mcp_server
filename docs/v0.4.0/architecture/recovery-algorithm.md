# Recovery Algorithm & Torn-State Policy (0.4.0)

This document specifies the deterministic recovery algorithm and torn-state resolution policy for 0.4.0.

## 1) Goals
- Deterministically resume the latest **non-terminal** transaction.
- Resolve torn-state conditions consistently.
- Guarantee that identical event sequences yield identical `next_action`.

---

## 2) Inputs (Canonical Sources)
- **Transaction Event Log** (append-only, canonical truth)
- **Materialized Transaction State** (derived, trusted only if integrity passes)

---

## 3) Recovery Algorithm (Deterministic)

### Step 0: Locate canonical artifacts
1. Resolve canonical artifact paths under `CWD/.agent/`.
2. Load event log (required).
3. Load materialized state (optional).

### Step 1: Validate materialized state
1. If materialized state is missing → skip to Step 3.
2. Verify `schema_version == "0.4.0"`.
3. Verify `integrity.state_hash` over canonical serialization.
4. Verify `last_applied_seq` and `integrity.rebuilt_from_seq` coherence.
5. If any check fails → mark materialized state **invalid**.

### Step 2: Decide precedence
- If materialized state is **valid** and `last_applied_seq` matches event log cursor → use it as current state.
- Otherwise → rebuild from event log.

### Step 3: Rebuild materialized state
1. Identify replay start (`start_seq`):
   - If valid snapshot/cursor exists: use its `last_applied_seq`.
   - Otherwise: `start_seq = 0`.
2. Replay event log from `start_seq` to latest valid `seq`.
3. Apply events to a fresh state projection (see invariants).
4. Compute `integrity.state_hash`, set `rebuilt_from_seq` and `last_applied_seq`.
5. Persist rebuilt materialized state.

### Step 4: Select target transaction
1. Find latest **non-terminal** transaction (no `tx.end.*`).
2. If none exists → resume next planned ticket (new `tx.begin`).
3. If multiple non-terminal tx appear due to corruption → select the highest valid `seq`.

### Step 5: Derive `next_action`
Derive `next_action` strictly from:
- `status` / `phase`
- `current_step` / `last_completed_step`
- `verify_state` / `commit_state`
- `file_intents` states

### Step 6: Emit resume boundary
- Emit `tx.step.enter` for the selected step before resuming work.

---

## 4) Torn-State Detection

A torn-state is detected when any of the following occurs:
- Materialized state integrity check fails.
- `last_applied_seq` does not correspond to the latest valid event `seq`.
- Materialized state references missing or invalid events.
- Multiple non-terminal transactions exist without valid ordering.
- File-intent states conflict with event ordering (e.g., `verified` before `verify.pass`).

---

## 5) Torn-State Resolution Policy

1. **Event log is canonical**: always prefer event log over materialized state.
2. **Discard invalid materialized state**: rebuild from log.
3. **Truncate corrupted tail**:
   - If invalid/corrupted events exist at the tail, truncate to the last valid `seq`.
4. **Rebuild deterministically**:
   - Apply events in `seq` order only.
   - Ignore duplicate `event_id` entries (record as dropped).

---

## 6) Transaction Selection Rules

- **Target**: latest non-terminal transaction.
- **Terminal**: `tx.end.done` or `tx.end.blocked`.
- If terminal exists for a `tx_id`, no further events for that tx are applied.
- If multiple candidates appear due to corruption, pick the highest valid `seq` and rebuild.

---

## 7) `next_action` Derivation Rules (Summary)

- If status is `planned`: `next_action = "tx.begin"`
- If status is `in-progress`:
  - If there are `file_intents` in `planned|started` → continue file operations.
  - If all intents are `applied` → move to verification.
- If status is `checking`:
  - If verify_state is `not_started` → `tx.verify.start`.
  - If verify_state is `failed` → fix and re-verify.
- If status is `verified`:
  - If commit_state is `not_started` → `tx.commit.start`.
- If status is `committed`: `tx.end.done`.

---

## 8) Determinism Guarantees

- Same event log → same materialized state → same `next_action`.
- No non-deterministic inputs are allowed in rebuild or selection.
- Resume always emits `tx.step.enter` before continuing work.

---

## 9) Notes
- This policy must align with lifecycle invariants in `lifecycle_invariants.md`.
- Legacy artifacts are not used as sources of truth in 0.4.0.