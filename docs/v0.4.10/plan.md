# Implementation Plan: 0.4.10 Resume-safety fixes

## Objectives
- Prevent agents from starting a new ticket when a non-terminal active transaction already exists.
- Make resume decisions clearer and safer by surfacing active transaction state and required next actions.
- Improve operator and agent guidance for copied or stale `.agent` state without weakening strict transaction ordering.
- Keep the release focused on active-transaction precedence, actionable resume guidance, and mismatch diagnostics.

## Background
Investigation of copied `.agent` artifacts showed a realistic resume-safety failure mode:

- `tx_state.json` can indicate an active transaction such as `p1-t1` with a non-terminal status like `checking`.
- An agent may still attempt to start `p1-t2` by choosing the next executable ticket instead of resuming the active transaction.
- In that case, runtime protections correctly reject the request with `tx_id does not match active transaction`.
- The current failure is safe, but the system does not yet provide enough proactive guidance to prevent the mistake early.
- Copied or stale `.agent` artifacts can add confusion during investigation, even when the primary issue is simply that unfinished active work must be resumed first.

## Problem Statement
The runtime currently protects transaction integrity, but resume guidance is not strong enough to ensure that agents and operators consistently:
1. prioritize `active_tx` over the next planned ticket,
2. understand the exact next required action for the active transaction, and
3. follow the safe recovery path instead of attempting to start the next ticket.

## Scope
### In scope
- Strengthen resume-oriented summaries and guidance
- Improve transaction-mismatch error messaging
- Update `.rules` so active transaction precedence is explicit
- Add tests that lock the intended resume behavior

### Out of scope
- Relaxing transaction ordering rules
- Allowing multiple concurrent active tickets
- Broad redesign of the state model
- Automatic migration or repair of copied `.agent` artifacts
- `project_root` mismatch detection as a feature for this release

## Phases

### Phase 1: Define the active-transaction precedence contract
**Goals**
- Clarify the expected behavior when a non-terminal active transaction exists.
- Define the contract that later implementation work must follow.

**Tasks**
- Define the rule that a non-terminal `active_tx` must always be resumed before any new ticket starts.
- Define the expected resume-guidance fields, including:
  - active ticket
  - active status
  - next required action
  - whether starting a new ticket is allowed
  - a short reason
- Document the checking-phase case where `p1-t1` remains active and `p1-t2` must not start.
- Align the contract across `draft.md`, `.rules`, and runtime expectations.

**Deliverables**
- Clear contract for active transaction precedence
- Clear contract for resume-oriented guidance fields
- Clear documented example for checking-phase resume behavior

---

### Phase 2: Runtime safety and messaging improvements
**Goals**
- Make the safe path obvious before a new ticket is started incorrectly.
- Improve diagnostics when a mismatch still occurs.

**Tasks**
- Update resume summary generation so it explicitly reports:
  - active ticket
  - active status
  - next required action
  - whether starting a new ticket is allowed
  - a short reason
- Improve `ops_start_task` and related mismatch errors so they explain:
  - current active transaction
  - requested ticket
  - required next action to recover safely
- Ensure copied or stale `.agent` context does not distract from the primary guidance to resume the active transaction first.
- Keep runtime behavior focused on actionable resume guidance and mismatch diagnostics.

**Deliverables**
- Stronger resume summaries
- More actionable transaction-mismatch errors
- Runtime behavior aligned with active-transaction precedence

---

### Phase 3: Rules, tests, and verification
**Goals**
- Keep behavior aligned between documentation, rules, and implementation.
- Prevent regressions in resume safety.

**Tasks**
- Update `.rules` to state explicitly that:
  - non-terminal `active_tx` must be resumed first
  - a new ticket must not start while an active transaction exists
  - the next executable ticket is selected only when there is no active transaction
- Add or extend tests for:
  - active transaction resume guidance
  - new-ticket blocking while a transaction is active
  - improved mismatch error messaging
  - copied-or-stale-state scenarios where active work still takes precedence
- Run verification and confirm the new contract is covered by tests.

**Deliverables**
- Updated rules text
- Regression tests for resume safety
- Verified implementation aligned with the new contract

## Acceptance Criteria
- Resume guidance clearly indicates when an active transaction must be resumed instead of starting a new ticket.
- Starting a new ticket while another non-terminal transaction is active remains blocked and produces an actionable error.
- `.rules`, runtime behavior, and tests agree on the active-transaction precedence contract.
- Copied or stale `.agent` context does not obscure the guidance to resume the active transaction first.
- Verification passes after the changes.

## Risks and Mitigations
- **Risk:** Messaging improvements may still leave ambiguity for agents.  
  **Mitigation:** Standardize required resume-summary fields and test for them directly.

- **Risk:** Copied or stale `.agent` context may broaden scope unnecessarily.  
  **Mitigation:** Keep the release focused on active transaction precedence, resume guidance, and actionable mismatch messaging.

- **Risk:** Rules and implementation may drift again.  
  **Mitigation:** Add contract-level tests covering both resume output and enforcement behavior.

## Verification Strategy
- Run the repository verification flow.
- Run targeted tests for resume summaries, task-start invariants, and actionable mismatch diagnostics.
- Confirm that improved error messages include the active transaction and recovery hint.
- Confirm that rules and implementation remain aligned.

## Rollout Notes
- Keep transaction-integrity guards strict.
- Prefer proactive guidance and explicit detection over silent recovery.
- Treat this release as a resume-safety improvement, not a workflow-model change.

## Phase 1 Completion Notes
- Phase 1 established the active-transaction precedence contract for `0.4.10`.
- The contract now treats any non-terminal `active_tx` as the first priority for resume decisions.
- Required resume-guidance fields are defined as:
  - active ticket
  - active status
  - next required action
  - whether starting a new ticket is allowed
  - a short reason
- The documented checking-phase example makes clear that when `p1-t1` remains active with `next_action=tx.verify.start`, the system must guide resume of `p1-t1` and must not allow `p1-t2` to start.
- This phase intentionally preserves strict runtime guards and exists to guide the implementation work in later phases.

## Phase 2 Progress Notes
- Implemented stronger mismatch diagnostics for active transaction conflicts in runtime code.
- `ops_start_task` now returns an actionable mismatch error that includes the active transaction, requested task, active ticket, current status, and next required action.
- Transaction invariant enforcement now reports active/requested transaction mismatch details and points callers back to the active transaction.
- `ops_resume_brief` now makes active work more explicit by reporting:
  - active ticket
  - active status
  - required next action
  - whether a new ticket may start
  - a short reason when resume is required
- Targeted regression coverage was added for:
  - mismatched task start attempts
  - mismatched task update attempts
  - resume brief output for checking-phase active work
  - state-store mismatch diagnostics
- Targeted tests for `tests/test_ops_tools.py` and `tests/test_state_store.py` passed after the Phase 2 changes.
- Repository verification also passed, so Phase 2 implementation work is now ready for final plan/ticket status updates and broader regression completion in Phase 3.

## Phase 3 Completion Notes
- Phase 3 completed the alignment work between rules, tests, and runtime behavior for `0.4.10`.
- The `.rules` contract now explicitly prioritizes resuming any non-terminal active transaction before selecting the next executable ticket.
- Regression coverage now locks the intended resume-safety behavior across:
  - active transaction resume guidance
  - blocking new-ticket starts while active work exists
  - actionable mismatch diagnostics for task start and task update flows
  - copied-or-stale `.agent` scenarios where active work still takes precedence
- Verification completed successfully after the Phase 3 updates.
- With phases 1 through 3 complete, the `0.4.10` plan now fully documents and verifies the active-transaction precedence contract.