# Implementation Plan: 0.5.3 Investigate and fix duplicate `tx.begin` transaction-log drift

## Objectives
- Identify the code path that allows duplicate `tx.begin` events to enter canonical transaction history.
- Restore confidence in replayed transaction state and resumability guarantees.
- Prevent invalid lifecycle-start writes before they reach the event log.
- Preserve strict replay and integrity behavior for malformed lifecycle history.
- Improve operational clarity for state-facing flows when historical invalidity already exists.
- Add regression coverage so duplicate-begin drift does not recur.

## Background
Version 0.5.2 clarified the machine-facing workflow contract around:

- canonical `.rules`,
- bootstrap-generated `.rules`,
- and workflow-driving tool responses for verify, commit, and terminal completion.

That work improved agent behavior around `committed` versus `done`, but it did not address a separate operational integrity problem observed during validation and state-capture follow-up.

The repository has shown an existing transaction-log integrity issue in which replay reports a `duplicate tx.begin`. When this occurs:

- replay metadata records an invalid event,
- rebuilt canonical state may diverge from the materialized snapshot,
- and some state-oriented follow-up operations surface integrity drift instead of completing cleanly.

This is not primarily a documentation issue. It is a transaction lifecycle integrity issue.

## Problem Statement
The current system can end up with duplicate lifecycle-start events in canonical transaction history.

In the observed failure mode:

- a `tx.begin` is appended for a transaction lifecycle,
- a second `tx.begin` appears for a lifecycle that should not have restarted that way,
- replay identifies the second begin as invalid,
- and state-capture or rebuild-oriented flows surface drift.

This degrades resumability because the AgentOps model depends on strict consistency between:

1. event append order,
2. replayed canonical transaction state,
3. persisted materialized `tx_state`,
4. and resume decisions derived from that state.

If duplicate begin events are possible, the system can no longer assume that replay and persisted state will remain aligned.

## Scope

### In scope
- Investigating how duplicate `tx.begin` events are produced.
- Tracing transaction-start code paths and lifecycle guards.
- Tightening begin-event validation and prevention logic.
- Verifying replay behavior for duplicate-begin history.
- Improving operational guidance when invalid history blocks canonical capture.
- Adding regression tests for begin-event integrity, replay behavior, and state-facing tooling behavior.

### Out of scope
- Redesigning the overall transaction model.
- Weakening integrity checks just to suppress drift failures.
- Treating malformed or duplicate lifecycle history as healthy state.
- Changing the 0.5.2 committed-versus-done workflow semantics.
- Broad refactors unrelated to transaction lifecycle integrity.

## Desired Outcome
After 0.5.3:

- normal workflows do not emit duplicate `tx.begin`,
- replay remains deterministic and strict,
- invalid lifecycle history is surfaced clearly and consistently,
- state capture succeeds when canonical history is valid,
- resume flows can reliably identify the correct active transaction,
- and regression coverage protects both prevention and detection behavior.

## Root Cause Areas to Investigate

### 1. Begin-event emission guards
A transaction-start path may allow `tx.begin` to be emitted when it should be rejected, for example when:

- a non-terminal active transaction already exists,
- the same transaction has already begun,
- or a resume/progress path mistakenly re-enters through lifecycle start.

### 2. Resume-path behavior
A resumed session may infer that it needs to start work again even though canonical history already contains the correct active lifecycle.

### 3. Replay and rebuild semantics
Replay may already classify duplicate begin events correctly, but surrounding flows may not consistently handle the resulting invalid state in a clear and operationally useful way.

### 4. Recovery and observability behavior
Once invalid history exists, state-facing flows may need better guidance around what is blocked, what is still safe, and what follow-up action is recommended.

## Design Principles

### 1. Preserve strict canonical history
The event log remains canonical. Fixes should strengthen confidence in replay, not weaken it.

### 2. Reject invalid writes early
It is better to block an invalid `tx.begin` at write time than to accept it and fail later during replay.

### 3. Prefer explicit failure over silent recovery
Invalid history should remain visible and diagnosable. The system should not silently invent a misleading best-effort state.

### 4. Separate prevention from remediation
0.5.3 should address both:

- prevention of new duplicate begin events,
- and clear handling of already-invalid historical logs.

## Implementation Strategy

### Phase 1: Reproduce and localize the duplicate-begin path
**Goals**
- Make the failure reproducible or at least traceable.
- Identify the transaction-start path responsible for the second begin event.

**Tasks**
- Review the observed invalid replay metadata and associated transaction identifiers.
- Trace transaction-start wrappers and any callers that can emit `tx.begin`.
- Determine whether the duplication occurs in:
  - normal start flow,
  - resume flow,
  - recovery flow,
  - or cross-session continuation.
- Document whether the duplicated begin uses the same transaction id, ticket id, and session context.

**Deliverables**
- Reproduction notes or a traced causal path.
- A narrowed list of lifecycle entry points involved in the invalid sequence.

---

### Phase 2: Tighten begin-event write guards
**Goals**
- Prevent duplicate lifecycle-start writes before they enter canonical history.
- Preserve valid start behavior for legitimate new transactions.

**Tasks**
- Review preconditions enforced before emitting `tx.begin`.
- Reject begin attempts when:
  - a non-terminal active transaction already exists,
  - the same transaction has already begun and is not terminal,
  - or the caller should be using update/resume semantics instead.
- Ensure error behavior is explicit and actionable rather than ambiguous.
- Confirm valid new transaction starts still work correctly.

**Deliverables**
- Hardened transaction-start validation.
- Clear failure semantics for invalid duplicate begin attempts.

---

### Phase 3: Clarify replay and integrity handling
**Goals**
- Keep replay strict for invalid lifecycle history.
- Make integrity outcomes easier to reason about operationally.

**Tasks**
- Review duplicate-begin classification in replay/rebuild logic.
- Confirm duplicate `tx.begin` remains an explicit integrity failure.
- Ensure rebuild metadata preserves:
  - invalid event details,
  - failure reason,
  - and enough context for diagnosis.
- Avoid any behavior that silently treats invalid history as healthy canonical state.

**Deliverables**
- Confirmed or improved replay classification for duplicate begin.
- Clearer integrity metadata and failure signaling.

---

### Phase 4: Improve state-facing operational clarity
**Goals**
- Make it clearer what happens when invalid history already exists.
- Reduce confusion in state capture, handoff, and resume-oriented flows.

**Tasks**
- Review behavior of state-facing operations when replay detects duplicate begin.
- Clarify what remains possible under invalid-history conditions, including:
  - state capture,
  - handoff export,
  - task summary,
  - and resume brief generation.
- Ensure blocked or degraded operations explain why they cannot proceed.
- Distinguish clearly between:
  - uninitialized logs,
  - valid empty logs,
  - and invalid lifecycle history.

**Deliverables**
- Better operational guidance for invalid-history conditions.
- More predictable behavior in state-facing workflows.

---

### Phase 5: Add regression coverage
**Goals**
- Prevent reintroduction of duplicate-begin write bugs.
- Protect replay/integrity behavior and operational clarity.

**Tasks**
- Add tests that reject duplicate `tx.begin` emission for active non-terminal transactions.
- Add tests for same-transaction duplicate begin attempts.
- Add tests that verify replay still classifies duplicate begin as invalid.
- Add tests that assert integrity metadata includes the expected invalid-event details.
- Add tests for state-facing behavior when duplicate-begin history exists.
- Verify legitimate begin/update/end flows still work after guard changes.

**Deliverables**
- Regression suite covering duplicate-begin prevention and detection.
- Tests protecting lifecycle-ordering and replay integrity guarantees.

## Candidate Work Areas
The likely implementation areas include:

- transaction lifecycle start helpers,
- task lifecycle wrappers that can begin work,
- replay/state rebuild logic,
- state capture and observability helpers,
- tests around lifecycle ordering, invalid-event handling, and resume behavior.

Exact file-level scope should be confirmed during implementation.

## Acceptance Criteria

### Duplicate-begin prevention
- Normal task-start flows do not emit duplicate `tx.begin` for an already-started non-terminal transaction.
- Same-transaction duplicate begin attempts are rejected with a clear error or failure result.
- Resume/progress flows no longer re-enter the lifecycle through an invalid begin path.

### Replay and integrity correctness
- Replay detects duplicate `tx.begin` deterministically.
- Duplicate begin remains an explicit integrity failure rather than being silently accepted.
- Rebuild metadata captures the invalid event and failure reason clearly.

### Operational clarity
- State-facing flows provide actionable guidance when invalid history blocks canonical capture.
- The system does not present invalid replay as healthy state.
- Behavior clearly distinguishes between uninitialized logs, valid empty logs, and invalid lifecycle history.

### Regression safety
- Tests fail if begin guards regress and permit duplicate lifecycle starts.
- Tests fail if replay stops surfacing duplicate begin as an integrity issue.
- Tests cover expected state-facing behavior when duplicate-begin history exists.

## Risks

### Medium behavioral risk
Tightened begin guards may expose existing caller assumptions that relied on invalid restart behavior.

**Mitigation**
- Keep validation rules explicit.
- Update callers that were implicitly depending on invalid begin behavior.
- Add tests for legitimate resume/update flows.

### Medium recovery-path risk
Historical logs that already contain duplicate begin events may continue to fail integrity checks until separately repaired or handled.

**Mitigation**
- Preserve strong diagnostics.
- Make operator guidance explicit.
- Separate prevention of new invalid events from handling of old invalid history.

### Low model risk
This work should not require a broader redesign of the transaction model.

**Mitigation**
- Keep the fix tightly focused on begin-event integrity, replay correctness, and state-facing operational clarity.
- Avoid unrelated lifecycle refactors.

## Validation Plan
After implementation, validation should include:

1. verifying that duplicate `tx.begin` can no longer be emitted through normal start/resume flows,
2. verifying that replay still flags historical duplicate begin as invalid,
3. verifying that integrity metadata remains understandable and complete,
4. verifying that state-facing workflows produce clear outcomes under invalid-history conditions,
5. verifying that normal begin, verify, commit, and end flows still work correctly.

## Ticket Breakdown

### Ticket `p1-t01`
**Title:** Reproduce duplicate `tx.begin` drift and trace the emitting path  
**Priority:** P0  
**Summary:** Identify how duplicate begin events are produced, whether the duplication is tied to start, resume, or recovery behavior, and which transaction lifecycle entry point needs to be fixed.

### Ticket `p1-t02`
**Title:** Prevent duplicate `tx.begin` emission through lifecycle-start guards  
**Priority:** P0  
**Summary:** Tighten transaction-start validation so invalid duplicate begin attempts are rejected before they enter canonical history.

### Ticket `p2-t01`
**Title:** Clarify replay, capture, and operational behavior for invalid begin history  
**Priority:** P1  
**Summary:** Keep replay strict for duplicate-begin history while improving metadata, operator guidance, and state-facing behavior when invalid lifecycle history already exists.

### Ticket `p3-t01`
**Title:** Add regression coverage for duplicate-begin prevention and detection  
**Priority:** P1  
**Summary:** Add tests that protect begin guards, replay classification, integrity metadata, and state-facing behavior for duplicate-begin scenarios.

## Expected Outcome
After 0.5.3:

- duplicate lifecycle starts should be prevented in normal operation,
- replay/state rebuild should remain strict and diagnosable,
- state-facing flows should behave more predictably under invalid-history conditions,
- and resumability should be more reliable under interruption, resume, and recovery.

## Summary
Version 0.5.3 should focus on investigating and fixing transaction-log drift caused by duplicate `tx.begin`.

The release should:

- identify the source of duplicate begin emission,
- prevent invalid lifecycle-start writes,
- preserve strict replay and integrity behavior,
- improve operational clarity when historical invalidity exists,
- and add regression coverage so the issue does not recur.