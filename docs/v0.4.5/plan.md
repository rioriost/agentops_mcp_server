# Implementation Plan: 0.4.5 bug fixes for tx event init alignment and transaction flow consistency

## 0.4.5 Positioning
- Starting work from an initialized-but-empty `tx_event_log.jsonl` currently triggers avoidable failures.
- The touched empty log created by `zed-agentops-init.sh` should be treated as a valid initial state, not as a broken transaction history.
- The workflow expectations in `.rules` and the actual MCP/server-side validation and ordering constraints are currently inconsistent.
- This release focuses on fixing those inconsistencies while preserving strict transaction safety and maintaining coverage of at least 90%.

## Objectives
- Treat an empty `tx_event_log.jsonl` as a valid initialized baseline.
- Align initialization, validation, and transaction ordering behavior with `.rules`.
- Eliminate the error cases listed in the updated draft where they indicate implementation/spec mismatches.
- Preserve strict validation for malformed tool inputs.
- Maintain coverage at 90% or higher.

---

## 1) Problem Statement
1. Jobs fail when `tx_event_log.jsonl` exists but contains no events.
2. Empty-log startup is not consistently interpreted as the same baseline produced by `zed-agentops-init.sh`.
3. Several transaction/tool contract expectations are out of sync between `.rules` and implementation, including:
   - required `actor`
   - required `payload`
   - required non-empty `session_id`
   - required `state` for state persistence
   - accepted values for `timezone`
4. Transaction ordering is enforced, but the required sequence is not consistently reflected in the planning/rules flow:
   - `tx.begin` must exist before task lifecycle events
   - `tx.verify.start` must exist before verify result events
   - `tx.verify.pass` must exist before file intents can move to `verified`
5. Invalid or stale transaction state snapshots can fail validation when status/phase/verify-state combinations drift from the canonical event flow.
6. The fixes must retain or improve test coverage to satisfy the 90% threshold.

---

## 2) Design Principles
1. **Init-safe, not validation-loose**  
   Empty event logs should be accepted as “no events yet,” while malformed inputs and invalid sequences should still fail fast.

2. **Canonical event-first transaction flow**  
   Transaction state must reflect valid event ordering rather than bypassing required lifecycle events.

3. **Spec and implementation alignment**  
   `.rules`, generated planning artifacts, and MCP/server behavior must describe the same required inputs and ordering.

4. **Minimal, targeted changes**  
   Focus only on initialization handling, transaction/tool validation, ordering enforcement, and their tests.

5. **Resumability remains primary**  
   Empty-log initialization and recovery paths must still preserve stable resume behavior under interruption.

---

## 3) Scope of Changes

### 3.1 Empty `tx_event_log.jsonl` handling
- Treat a present-but-empty `tx_event_log.jsonl` as a valid initialized state.
- Ensure transaction state rebuild/load paths interpret an empty file as zero events, not as an error condition.
- Align empty-log semantics with the baseline created by `zed-agentops-init.sh`.
- Distinguish clearly between:
  - missing log file
  - empty log file
  - malformed/non-parseable log contents

### 3.2 Transaction/tool input validation alignment
- Keep strict validation for required transaction inputs.
- Confirm and standardize the following contracts:
  - `tx_event_append`
    - `actor` is required and must match the accepted structure
    - `payload` is required and must be an object
    - `session_id` is required and must be non-empty
  - `tx_state_save`
    - `state` is required and must satisfy schema/enum constraints
  - task start/progress lifecycle
    - task lifecycle events must not be emitted before `tx.begin`
  - time lookup
    - `timezone` accepts only supported enum values such as `utc` and `local`
- Normalize error messages so they are actionable and consistent with the documented workflow.

### 3.3 Transaction ordering consistency
- Enforce and document valid ordering across transaction lifecycle operations:
  - `tx.begin` before task lifecycle events
  - `tx.verify.start` before `tx.verify.pass` / `tx.verify.fail`
  - `tx.verify.pass` before `tx.file_intent.update` with `state=verified`
  - file intent update to applied/verified only after the corresponding file intent exists
- Review commit gating so commit operations depend on a valid verify sequence rather than ad hoc state mutations.

### 3.4 State schema and transition consistency
- Fix or clarify state transitions that currently allow invalid combinations such as:
  - invalid `verify_state.status`
  - phase/status mismatch
  - mutated file-intent states unsupported by canonical ordering
- Ensure persisted transaction state can be reconstructed from events without validation drift.
- Prefer event-driven state transitions over direct snapshot mutation where possible.

### 3.5 Documentation and planning contract alignment
- Update `.rules` so the documented operating procedure matches actual server/tool behavior.
- Ensure plan/ticket generation for this version explicitly reflects the required transaction sequence and validation rules.
- Make init-safe empty-log handling explicit in the operational rules to avoid future divergence.

### 3.6 Tests and coverage
- Add or update tests for:
  - empty-log startup and rebuild behavior
  - missing vs empty vs malformed event log distinctions
  - required input validation for transaction-related tools
  - ordering failures for begin/verify/file-intent transitions
  - state validation around verify/phase/status consistency
- Confirm total coverage remains at or above 90%.

---

## 4) Phases and Tasks

### Phase 1: Analysis and contract definition
**Goal:** Trace the failures from the updated draft to concrete code paths and define the correct behavior.

- **p1-t1**: Inventory empty-log init flow, validation touchpoints, and ordering enforcement paths.
- **p1-t2**: Define the corrected behavior contract for initialization, validation, ordering, and state transitions.

### Phase 2: Implementation
**Goal:** Fix runtime behavior so initialization and transaction flow are robust and consistent.

- **p2-t1**: Implement empty-log-safe initialization and rebuild behavior.
- **p2-t2**: Align required input validation and error messaging for transaction-related operations.
- **p2-t3**: Tighten transaction ordering and file-intent transition enforcement.
- **p2-t4**: Correct state transition/schema handling for verify, phase, and status consistency.

### Phase 3: Rules and docs alignment
**Goal:** Bring `.rules` and generated planning expectations into sync with implementation.

- **p3-t1**: Update `.rules` for init-safe empty-log handling and required tool input contracts.
- **p3-t2**: Update `.rules` for canonical transaction ordering, task lifecycle prerequisites, and commit gating expectations.

### Phase 4: Tests and verification
**Goal:** Prove the fixes and preserve release quality.

- **p4-t1**: Add unit/integration tests for empty-log initialization and transaction validation failures.
- **p4-t2**: Add regression tests for ordering and state-transition invariants.
- **p4-t3**: Run verification and confirm coverage is at least 90%.

---

## 5) Acceptance Criteria Mapping

### Empty-log initialization
- Starting from a touched but empty `tx_event_log.jsonl` does not raise an error.
- Empty log behavior matches the initialized baseline expected from `zed-agentops-init.sh`.
- Missing, empty, and malformed log cases are handled distinctly and predictably.

### Validation alignment
- Required inputs are validated consistently and produce clear errors.
- Transaction/task lifecycle operations fail fast when prerequisites are missing.
- Supported timezone values are enforced consistently.

### Ordering alignment
- Task lifecycle events cannot start before `tx.begin`.
- Verify result events cannot occur before `tx.verify.start`.
- File intent `verified` transitions cannot occur before successful verification.
- Commit gating follows the canonical verify flow.

### State consistency
- Persisted transaction state satisfies schema constraints.
- Phase/status/verify-state combinations are internally consistent.
- State rebuilt from events remains valid.

### Quality gate
- Tests pass.
- Coverage is at least 90%.

---

## 6) Risks and Mitigations
- **Risk:** Empty-log support could accidentally relax malformed-log handling.  
  **Mitigation:** Treat only zero-event files as valid; keep parse/schema failures strict.

- **Risk:** Updating `.rules` without matching implementation could create more workflow confusion.  
  **Mitigation:** Define implementation contract first, then update `.rules` to match exactly.

- **Risk:** Direct state-save flows may still bypass canonical ordering.  
  **Mitigation:** Add regression tests around event-first transitions and snapshot validation.

- **Risk:** Tightened validation may break previously tolerated but invalid usage.  
  **Mitigation:** Keep error messages explicit and align generated docs/tickets with the required sequence.

---

## 7) Deliverables
- Regenerated `docs/v0.4.5/plan.md`
- Regenerated `docs/v0.4.5/tickets_list.json`
- Regenerated `docs/v0.4.5/pX-tY.json` ticket files
- Source changes for empty-log initialization, validation alignment, ordering enforcement, and state consistency
- Test updates/regressions demonstrating compliance
- Verification results confirming coverage ≥ 90%