# 0.4.0 Verification Gates and Coverage Targets

This document defines the verification gates for Phase 3 and the coverage target for 0.4.0. It specifies *what* must be validated and *when* validation is required, without implementing tests.

## 1. Coverage Target

- **Minimum coverage**: >= 90% line coverage across the Python package.
- Coverage must be measured using the existing project test runner configuration.
- The coverage report must be captured for every verification pass.

## 2. Verification Gates (Required)

### Gate A: Deterministic Rebuild
**Purpose:** Ensure rebuild from event log yields equivalent materialized state.

**Must verify:**
- Rebuild from event log up to `last_applied_seq` yields identical `state_hash`.
- Rebuild is deterministic for identical event sequences.
- Rebuild fails fast on schema mismatch and logs a clear summary.

**Pass criteria:**
- Rebuild succeeds and hashes match for all test scenarios.

---

### Gate B: Interruption Recovery
**Purpose:** Ensure all interruption cut points resume deterministically.

**Must verify (per interruption matrix):**
- Resume targets the latest non-terminal transaction.
- `next_action` is identical for the same persisted artifacts.
- Torn-state is resolved by log-first recovery policy.

**Pass criteria:**
- All interruption scenarios recover with correct transaction and action.

---

### Gate C: Intent Integrity
**Purpose:** Ensure file intent semantics are enforced.

**Must verify:**
- File intent exists before mutation.
- File intent states are monotonic.
- File intent states reconcile after rebuild.

**Pass criteria:**
- All intent invariants hold under both normal and rebuild paths.

---

### Gate D: Verify/Commit Sequencing
**Purpose:** Ensure verification and commit gates enforce ordering.

**Must verify:**
- `tx.verify.start` precedes `tx.verify.pass|fail`.
- `tx.commit.start` occurs only after `tx.verify.pass`.
- `tx.end.done` occurs only after `tx.commit.done`.

**Pass criteria:**
- Any illegal sequence is rejected or results in deterministic block.

---

### Gate E: Resume Selection Logic
**Purpose:** Ensure consistent selection of active transaction.

**Must verify:**
- Latest non-terminal transaction is always selected.
- If none exists, a new transaction begins deterministically.
- Multiple non-terminal transactions triggers invariant violation path.

**Pass criteria:**
- Selection and `next_action` are deterministic for all cases.

---

## 3. Required Evidence for Verification

Each verification run must capture:

- Coverage report (>= 90%).
- Log excerpt or summary of rebuild checks.
- Results for each gate (pass/fail).
- Short summary of any recovery behavior (if applicable).

## 4. Failure Handling Policy

- Any gate failure blocks release for 0.4.0.
- Failures must include:
  - Gate name
  - Short summary
  - Relevant sequence or step identifier
  - Suggested remediation path (if known)