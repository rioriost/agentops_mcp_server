# Implementation Plan: 0.4.12 Tx state synchronization and canonical workflow recovery

## Objectives
- Restore strict synchronization between `.agent/tx_event_log.jsonl` and `.agent/tx_state.json`.
- Ensure task lifecycle, verification, commit, rebuild, and resume flows all observe the same canonical transaction state.
- Prevent silent drift between appended transaction events and the materialized transaction snapshot.
- Improve observability and regression protection for workflow guard failures caused by stale or inconsistent transaction state.

## Background
Recent execution exposed a mismatch between the canonical event log and the materialized transaction state.

Observed symptoms included:
- `commit.start requires verify.pass`
- `tx.begin required before other events`
- `verify.start emitted but tx_state was not updated to running`

At the same time, the event log already contained later-stage events such as:
- `tx.verify.pass`
- `tx.commit.done`
- `tx.end.done`
- a later `tx.begin` for the next ticket

This indicates that event progression was recorded, but downstream workflow guards still evaluated state as if the progression had not been fully materialized.

## Problem Statement
The current implementation can allow the canonical event log and the materialized transaction state to diverge.

This creates failure modes such as:
1. `tx.begin` exists in the event log, but task lifecycle tools still reject follow-up actions as if no transaction has started.
2. verify events exist in the event log, but commit gating still rejects the transaction as unverified.
3. rebuild or capture logic leaves `last_applied_seq` looking current while `active_tx` still reflects stale or default state.
4. the system falls back to "no active transaction" even though newer event-log entries clearly define one.
5. failure diagnostics appear only as downstream guard errors instead of explicit synchronization or integrity failures.

The release should make the synchronization contract explicit in implementation behavior and protect it with tests.

## Scope

### In scope
- Synchronization between event append and materialized state updates
- Guard consistency across task lifecycle, verify, and commit flows
- Active transaction reconstruction during rebuild and resume
- Drift detection between event log and materialized transaction state
- Improved synchronization failure diagnostics and error logging
- Regression tests for the observed mismatch scenarios

### Out of scope
- Relaxing strict workflow guard behavior
- Changing the ticket status enum
- Replacing the canonical event log model
- Introducing a secondary best-effort transaction tracker
- Broad redesign of planning artifacts unrelated to state synchronization

## Phases

### Phase 1: Define the synchronization contract and failure boundaries
**Goals**
- Make the expected synchronization behavior explicit in implementation guidance.
- Identify the exact boundaries where event-log progression and materialized state must remain coupled.

**Tasks**
- Define the canonical synchronization points for:
  - `tx.begin`
  - task lifecycle updates
  - `tx.verify.start`
  - `tx.verify.pass` / `tx.verify.fail`
  - `tx.commit.start` / `tx.commit.done` / `tx.commit.fail`
  - `tx.end.done` / `tx.end.blocked`
- Define the expected relationship between:
  - appended transaction events,
  - `last_applied_seq`,
  - `active_tx`,
  - `verify_state`,
  - `commit_state`
- Define which failures should surface as explicit integrity or synchronization errors instead of downstream guard errors.
- Define how active transaction reconstruction should behave when:
  - a terminal `tx.end.*` is followed by a later `tx.begin`
  - multiple sessions exist in the same event log
  - the log is current but the materialized state is stale or defaulted

**Deliverables**
- Explicit synchronization contract for event append and state materialization
- Explicit failure model for state drift and stale-state guard behavior
- Explicit active-transaction reconstruction rules for rebuild and resume

---

### Phase 2: Fix canonical state synchronization in runtime flows
**Goals**
- Ensure all runtime helpers update or validate materialized transaction state consistently with the event log.
- Eliminate cases where different workflow helpers disagree on transaction state.

**Tasks**
- Update the runtime flow so event append and state persistence remain coupled at each canonical transition.
- Ensure task lifecycle helpers observe a `tx.begin` as active once it has been recorded.
- Ensure verify helpers update transaction state so commit gating sees the same verified transaction context.
- Ensure commit helpers reject only true sequencing violations, not stale-state artifacts caused by missing materialization.
- Prevent partial progression where events advance but state remains at an older lifecycle stage.
- Ensure guard checks use a consistent canonical transaction view across task, verify, and commit operations.

**Deliverables**
- Runtime fixes for synchronized event/state progression
- Consistent guard behavior across lifecycle, verify, and commit flows
- Reduced downstream failures caused by stale transaction snapshots

---

### Phase 3: Fix rebuild, capture, and recovery behavior
**Goals**
- Ensure rebuild and capture flows materialize the correct active transaction from the event log.
- Prevent default or stale transaction snapshots from being treated as current.

**Tasks**
- Update rebuild logic so the most recent valid active transaction is reconstructed correctly from the event log.
- Ensure `tx.end.*` followed by a later `tx.begin` makes the later transaction active in the rebuilt state.
- Ensure `last_applied_seq` cannot advance without the associated `active_tx` payload reflecting the same event horizon.
- Review session-aware behavior and make active transaction selection deterministic when multiple session identifiers appear in the log.
- Ensure capture flows do not overwrite valid active transaction state with default "none" state unless that is truly the canonical result.

**Deliverables**
- Correct active-transaction reconstruction from canonical events
- Safer rebuild and capture behavior under interruption and recovery
- Stronger protection against stale or empty materialized state being treated as current

---

### Phase 4: Improve observability and add regression protection
**Goals**
- Make synchronization failures diagnosable from `.agent` artifacts.
- Prevent regression in event/state synchronization behavior.

**Tasks**
- Improve structured error logging so synchronization failures include:
  - expected transaction state
  - observed transaction state
  - relevant event sequence
  - active ticket id
  - session context
  - guard or validation point
- Add or extend tests covering:
  - `tx.begin` present in the log but lifecycle helpers still rejecting follow-up actions
  - verify events present in the log but commit gating still rejecting with missing verify state
  - stale or empty `active_tx` after rebuild despite later events
  - `last_applied_seq` advancing without matching `active_tx` updates
  - transition from `tx.end.done` to a later `tx.begin`
  - synchronization and guard failure logging to `.agent/errors.jsonl`
- Run repository verification and any targeted tests for synchronization, rebuild, and error logging behavior.

**Deliverables**
- Better synchronization diagnostics in `.agent/errors.jsonl`
- Regression tests for observed mismatch scenarios
- Verification evidence for the 0.4.12 release

## Acceptance Criteria
- A transaction that emits `tx.begin` is recognized as active by subsequent task lifecycle operations.
- A transaction that emits successful verify events is recognized as verified by commit gating.
- Materialized transaction state stays synchronized with event-log progression at each canonical lifecycle transition.
- `last_applied_seq` cannot indicate a fully applied state while `active_tx` remains stale, empty, or inconsistent with the latest events.
- Rebuild logic materializes the latest active transaction correctly from the event log.
- `tx.end.done` followed by a later `tx.begin` results in the later transaction becoming active.
- Synchronization failures are surfaced clearly enough to diagnose root cause from `.agent/errors.jsonl` and related canonical state artifacts.
- Regression tests cover the observed event-log / state mismatch scenarios.
- Repository verification passes with the fixes in place.

## Risks and Mitigations
- **Risk:** Fixes may patch individual guard errors without addressing the underlying synchronization contract.  
  **Mitigation:** Treat event append and state materialization as one canonical progression path and validate the relationship directly.

- **Risk:** Rebuild logic may still mishandle edge cases involving terminal events followed by new transactions.  
  **Mitigation:** Add explicit tests for `tx.end.*` to later `tx.begin` handoff behavior.

- **Risk:** Session-aware reconstruction may become ambiguous if multiple sessions share the same log.  
  **Mitigation:** Define deterministic selection rules and cover mixed-session cases with targeted tests.

- **Risk:** Observability improvements may remain too vague to help operators diagnose state drift.  
  **Mitigation:** Require structured error fields for expected state, observed state, event sequence, ticket id, and session context.

## Verification Strategy
- Run repository verification.
- Add targeted tests for task lifecycle, verify, commit, rebuild, and capture synchronization behavior.
- Reproduce the previously observed failure patterns with automated tests.
- Confirm that `.agent/errors.jsonl` captures synchronization failures with actionable context.
- Confirm that rebuilt and captured transaction state remains aligned with the canonical event log.

## Rollout Notes
- Keep 0.4.12 focused on canonical state synchronization and workflow integrity.
- Prefer fixing the synchronization contract and reconstruction logic over weakening strict guard behavior.
- Treat resumability and deterministic recovery as the primary release outcomes.