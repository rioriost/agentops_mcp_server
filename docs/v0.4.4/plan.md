# Implementation Plan: 0.4.4 bug fixes for tool sequencing & transaction integrity

## 0.4.4 Positioning
- 0.4.3 usage revealed multiple defects in MCP tool sequencing and transaction handling.
- `.rules` enforcement is stricter than current `src/` implementations.
- Aim: eliminate tool-ordering errors and stabilize transaction state rebuild.

## Objectives
- Align `src/` tool implementations with `.rules` sequencing requirements.
- Prevent transaction state rebuild from halting due to invalid event ordering.
- Ensure tool calls behave correctly under strict transaction lifecycle rules.
- Maintain coverage >= 90%.

## Scope

### In scope
- MCP tool sequencing correctness (`commit_if_verified`, `ops_start_task`, `ops_update_task`).
- Event log ordering and transaction state rebuild behavior.
- Tightening `.rules` compliance in tool implementations.

### Out of scope
- Large refactors beyond sequencing and transaction lifecycle correctness.
- Feature additions unrelated to transaction ordering.
- Non-transactional tool changes.

---

## 1) Problem Statement (Normalized)
Observed errors from 0.4.3 usage:

1. `commit_if_verified` fails with:
   - `verify result requires verify.start`
   - Root cause: verify lifecycle events are missing or out of order.

2. `ops_start_task` fails with:
   - `active transaction already in progress`
   - Root cause: transaction lifecycle state is inconsistent with event log.

3. `ops_update_task` fails with:
   - `tx_id does not match active transaction`
   - Root cause: tx_state rebuild halts due to invalid event log ordering (e.g., `tx.commit.start` without `tx.begin`/`verify.start`).

---

## 2) Design Principles (0.4.4)
1. **Canonical lifecycle enforcement**
   - Single active transaction; state must match event log.
2. **Order correctness**
   - `verify.start` must precede verify results and commit actions.
3. **Minimal safe change**
   - Fix ordering and validation only; avoid unrelated refactors.
4. **Coverage preservation**
   - Keep test coverage >= 90%.

---

## 3) Target Changes

### 3.1 Verify/Commit ordering
- Enforce `verify.start` before any verify result is accepted.
- Gate `commit_if_verified` on successful verify lifecycle.
- Provide clear error messages when ordering is invalid.

### 3.2 Transaction start/update consistency
- Disallow `ops_start_task` when an unrelated active transaction exists.
- Require `ops_update_task` to match current `tx_id` or return a clear error.

### 3.3 Event ordering & rebuild stability
- Ensure canonical ordering: event append → tx_state update → cursor persist.
- Prevent event log sequences that can halt rebuild (`tx.commit.start` without `tx.begin`/`verify.start`).

### 3.4 Tests & coverage
- Add tests for:
  - verify lifecycle ordering
  - duplicate start prevention
  - tx_id mismatch error behavior
  - commit gating on verify success
- Validate coverage >= 90%.

---

## 4) Phases & Tasks

### Phase 1: Analysis & Planning
- **p1-t1**: Inventory sequencing violations and lifecycle flow.
- **p1-t2**: Draft sequencing enforcement plan.

### Phase 2: Implementation
- **p2-t1**: Enforce verify lifecycle ordering for `commit_if_verified`.
- **p2-t2**: Harden start/update logic (start gating + tx_id validation).
- **p2-t3**: Ensure canonical event ordering (append → state → cursor).

### Phase 3: Tests
- **p3-t1**: Add tests for verify/commit gating and tx mismatch errors.
- **p3-t2**: Validate coverage remains >= 90%.

### Phase 4: Verification & Release
- **p4-t1**: Run verification suite.
- **p4-t2**: Confirm acceptance criteria.

---

## 5) Acceptance Criteria
- No tool errors for correct sequencing:
  - `commit_if_verified` succeeds after verify lifecycle.
  - `ops_start_task` handles existing transactions correctly.
  - `ops_update_task` rejects mismatched `tx_id`, succeeds when aligned.
- Transaction state rebuild completes without halting on invalid event ordering.
- Test coverage >= 90%, tests pass.

---

## 6) Risks & Mitigations
- **Risk:** Hidden sequencing behavior in other tool wrappers.
  - **Mitigation:** Search all `src/` tools for verify/commit/task lifecycle handling.
- **Risk:** Tight ordering breaks existing workflows.
  - **Mitigation:** Keep changes minimal and add tests capturing expected sequences.

---

## 7) Deliverables
- Updated `docs/v0.4.4/plan.md`
- Updated tickets in `docs/v0.4.4/` matching revised plan
- Source fixes in `src/` for sequencing enforcement
- Tests covering ordering and mismatch handling