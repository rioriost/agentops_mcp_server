# Writer Pipeline Specification (0.4.0)

This document defines the canonical writer pipeline, ordering guarantees, and torn-state handling for 0.4.0.

## 1) Goals
- Preserve deterministic resume by enforcing a strict write order.
- Minimize torn-state ambiguity under interruption.
- Ensure materialized state can be rebuilt from the event log.

## 2) Canonical Ordering (Required)
For every mutation-affecting step, the writer MUST execute:

1. **Append event(s) to transaction event log**
2. **Update materialized transaction state**
3. **Persist state cursor (`last_applied_seq`) atomically with state**

This order is mandatory and mirrors WAL-style durability:
`event append → state update → cursor persist`.

## 3) Pipeline Steps (Detailed)

### Step 0: Resolve artifacts
- Resolve canonical artifact paths under `CWD/.agent/`.
- Ensure the event log exists (create if missing).

### Step 1: Append event(s)
- Append `tx.*` events in strict `seq` order.
- Reject events missing required envelope fields.
- Enforce intent-before-mutation invariants (see `lifecycle_invariants.md`).

### Step 2: Apply to materialized state
- Apply new events to a fresh in-memory projection.
- Update `active_tx` fields (status, step, verify/commit state, file intents).
- Update semantic memory (see `semantic-memory-rules.md`).

### Step 3: Persist state + cursor
- Write materialized state with updated `last_applied_seq`.
- Compute `integrity.state_hash` over canonical serialization.
- Persist `updated_at` and `integrity.rebuilt_from_seq` as applicable.

### Step 4: Derived views (optional)
- Regenerate handoff or human-readable summaries **only after** state persistence.
- Derived views are not canonical sources of truth.

## 4) Atomicity & Torn-State Expectations
- If interruption occurs:
  - **After Step 1 only**: event log is ahead → rebuild from log.
  - **After Step 2 but before Step 3**: state is stale → rebuild from log.
  - **After Step 3**: state is coherent if `state_hash` validates.

## 5) Failure Handling
- On invalid event or invariant violation:
  - Reject the event, do not update state.
- On failed state persistence:
  - Treat state as invalid on next start and rebuild from log.
- On corrupted tail events:
  - Truncate to last valid `seq` and rebuild.

## 6) Idempotency Rules
- Replaying the same `seq` range yields identical materialized state.
- Duplicate `event_id` entries are ignored and counted as `dropped_events`.

## 7) Alignment
- Must align with:
  - `schema/materialized_state.md`
  - `architecture/recovery-algorithm.md`
  - `architecture/lifecycle_invariants.md`
