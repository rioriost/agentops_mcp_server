# 0.4.0 Interruption Cut Point Matrix

This matrix defines interruption cut points to validate deterministic recovery. Each cut point includes expected canonical state, rebuild outcome, and resume action.

## Scope
- Applies to transaction lifecycle from `tx.begin` through `tx.end.*`.
- Focuses on boundaries where durability or ordering can be torn.

## Legend
- **EL**: Event Log
- **MS**: Materialized State
- **Cursor**: `last_applied_seq`

---

## A. Before First File Mutation

### A1. After `tx.begin`, before any `tx.step.enter`
- **Cut point**: process stops after `tx.begin` append.
- **EL**: has `tx.begin`.
- **MS**: may be stale or missing.
- **Expected recovery**:
  - Rebuild -> active tx in `planned`/`in-progress`.
  - `next_action`: enter first step (`tx.step.enter`).

### A2. After `tx.step.enter`, before any file intent registration
- **Cut point**: `tx.step.enter` appended, no file intents yet.
- **Expected recovery**:
  - Rebuild -> active tx, step set.
  - `next_action`: register file intents for upcoming mutations.

---

## B. Between Intent Registration and Mutation

### B1. After `tx.file_intent.add`, before `tx.file_intent.start`
- **Cut point**: intent registered, mutation not started.
- **Expected recovery**:
  - Rebuild -> file intent state `planned`.
  - `next_action`: emit `tx.file_intent.start` then mutate.

### B2. After `tx.file_intent.start`, before mutation completes
- **Cut point**: mutation in-flight.
- **Expected recovery**:
  - Rebuild -> intent state `started`.
  - `next_action`: re-apply or verify mutation result, then `tx.file_intent.apply`.

---

## C. After Mutation, Before State Persist

### C1. After `tx.file_intent.apply`, before `tx.state.persist`
- **Cut point**: EL has apply; MS not updated.
- **Expected recovery**:
  - Rebuild -> intent state `applied`.
  - `next_action`: persist state and continue; verify if required.

---

## D. After State Persist, Before Verify

### D1. After `tx.state.persist`, before `tx.verify.start`
- **Cut point**: MS and cursor updated; verify not started.
- **Expected recovery**:
  - Integrity valid; no rebuild needed.
  - `next_action`: start verification.

---

## E. During Verification

### E1. After `tx.verify.start`, before `tx.verify.pass|fail`
- **Cut point**: verification in progress.
- **Expected recovery**:
  - Rebuild -> verify state `started`.
  - `next_action`: re-run verification and emit pass/fail.

### E2. After `tx.verify.fail`, before remediation step
- **Cut point**: failure recorded, no remediation yet.
- **Expected recovery**:
  - Rebuild -> status `checking` (or policy-defined regression).
  - `next_action`: enter remediation step and fix.

---

## F. After Verify Pass, Before Commit

### F1. After `tx.verify.pass`, before `tx.commit.start`
- **Cut point**: verification passed; commit not started.
- **Expected recovery**:
  - Rebuild -> verify state `passed`.
  - `next_action`: start commit.

---

## G. During Commit

### G1. After `tx.commit.start`, before `tx.commit.done|fail`
- **Cut point**: commit in progress.
- **Expected recovery**:
  - Rebuild -> commit state `started`.
  - `next_action`: retry commit or mark failure.

### G2. After `tx.commit.done`, before `tx.end.done`
- **Cut point**: commit succeeded; transaction not ended.
- **Expected recovery**:
  - Rebuild -> status `committed`.
  - `next_action`: emit `tx.end.done`.

---

## H. Terminal and Post-Terminal

### H1. After `tx.end.done`
- **Cut point**: transaction terminal.
- **Expected recovery**:
  - No active tx resumed.
  - `next_action`: start next planned ticket.

### H2. After `tx.end.blocked`
- **Cut point**: blocked terminal.
- **Expected recovery**:
  - No active tx resumed.
  - `next_action`: surface block reason; await operator action.

---

## I. Integrity Mismatch / Torn State

### I1. MS hash mismatch vs rebuild
- **Cut point**: MS present but integrity fails.
- **Expected recovery**:
  - Discard MS, rebuild from EL.
  - `next_action`: derived from rebuilt state only.

### I2. Corrupt tail event in EL
- **Cut point**: invalid record at log tail.
- **Expected recovery**:
  - Truncate to last valid `seq`, rebuild.
  - `next_action`: resume at last valid boundary.

---

## Acceptance
- Each cut point must be tested with deterministic outcomes.
- Rebuild results must match expected `next_action` and state invariants.