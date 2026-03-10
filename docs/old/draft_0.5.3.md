# Draft for 0.5.3: investigate and fix transaction-log drift caused by duplicate `tx.begin`

## Background

Version 0.5.2 clarified the machine-facing workflow contract for:

- canonical `.rules`,
- bootstrap-generated `.rules`,
- and workflow-driving tool responses around verify, commit, and terminal task completion.

That work improved agent guidance and made the distinction between non-terminal `committed` and terminal `done` much more explicit.

During validation and follow-up state capture, however, the repository continued to show an operational integrity problem unrelated to the 0.5.2 contract clarification itself:

- transaction-log replay reported an existing `duplicate tx.begin`,
- rebuild/state-capture flows surfaced integrity drift,
- and some state-oriented follow-up operations could not complete cleanly because canonical replay no longer matched the materialized state as expected.

This indicates that the next release should focus on transaction-log integrity and replay correctness.

## Problem

The current system can encounter a condition where the transaction event log contains a duplicate `tx.begin` for a transaction lifecycle that should not have been started twice.

When this happens, downstream behavior becomes unreliable in ways that matter for resumability:

- transaction-state rebuild may detect integrity drift,
- state capture may fail or refuse to persist a rebuilt canonical snapshot,
- resume logic may become harder to trust,
- and handoff/state-oriented workflows may see a mismatch between expected active transaction state and replayed history.

The issue has already been observed in practice as a `duplicate tx.begin` condition associated with transaction replay and integrity checking.

## Why this matters

The AgentOps model depends on a strict relationship between:

1. appended lifecycle events,
2. replayed canonical transaction state,
3. materialized `tx_state`,
4. and resume decisions derived from that state.

If duplicate lifecycle-start events are allowed to enter the log without a well-defined outcome, several guarantees weaken:

- active transaction detection becomes less trustworthy,
- rebuild results may diverge from the materialized snapshot,
- session interruption recovery becomes less reliable,
- and tools that depend on canonical state may refuse to proceed even when the repository contents themselves are otherwise fine.

This is not just a cosmetic logging problem. It is a resumability and workflow-integrity problem.

## Observed symptom

The observed failure mode is:

- replay/integrity logic reports a `duplicate tx.begin`,
- rebuild metadata records that condition as an invalid event,
- and state-oriented operations surface drift rather than silently treating the log as clean.

This behavior is preferable to silently corrupting the workflow state, but it still leaves the repository in a degraded operational state until the root cause is fixed.

## Root cause hypothesis

The likely root causes fall into one or more of the following categories:

### 1. Lifecycle guard gaps

A transaction-begin path may be allowing `tx.begin` to be emitted even when:

- an active non-terminal transaction already exists,
- the same transaction identifier has already begun,
- or the caller is resuming work that should have used progress/update events rather than a fresh begin event.

### 2. Replay validation gaps

Replay logic may correctly detect duplicate begin events, but the surrounding system may not consistently prevent or remediate the condition before later persistence/capture steps run.

### 3. Cross-session or resume-path ambiguity

A resumed session may be reconstructing intent from partial state and mistakenly attempting to start a transaction that canonical history already considers active or already begun.

### 4. Incomplete recovery semantics

Once a duplicate begin exists in the log, current state-capture/rebuild behavior may not provide a sufficiently clear operational path for:

- continued safe work,
- explicit repair,
- or bounded recovery without manual intervention.

## Goal

For 0.5.3, investigate and fix the duplicate-`tx.begin` drift issue so that canonical transaction replay remains trustworthy and resumability guarantees are restored.

The system should ensure that:

- duplicate begin events are prevented wherever possible,
- replay detects invalid begin sequences consistently,
- recovery behavior is explicit and safe,
- and state capture/resume flows remain operational when the repository is otherwise healthy.

## Desired outcome

After 0.5.3:

- duplicate `tx.begin` events should no longer be emitted during normal operation,
- transaction replay should remain deterministic and integrity-preserving,
- state capture should succeed when canonical history is valid,
- resume flows should reliably identify the correct active transaction,
- and any remaining invalid-log conditions should produce clear, actionable outcomes.

## Scope

### In scope

- investigating how duplicate `tx.begin` events are produced,
- tightening lifecycle guards around transaction start,
- validating replay behavior for duplicate-begin scenarios,
- improving error/reporting semantics around invalid transaction-log history,
- adding regression coverage for begin-event integrity and replay behavior.

### Out of scope

- redesigning the entire transaction model,
- weakening integrity checks just to suppress drift errors,
- treating malformed logs as valid history,
- broad refactors unrelated to transaction lifecycle integrity,
- changing the committed-versus-done workflow clarified in 0.5.2.

## Non-goals

This draft does not propose:

- collapsing lifecycle phases,
- replacing event-log replay with a different state model,
- removing strict invalid-event detection,
- or papering over duplicate begin events by silently ignoring them without clear policy.

The goal is to fix the cause and make invalid-state handling explicit, not to hide the problem.

## Investigation plan

## 1. Reproduce the duplicate-`tx.begin` path

Create or identify a deterministic reproduction for the observed failure.

The investigation should answer:

- which code path emits the second begin event,
- whether the duplication happens in normal task start, resume, or recovery flows,
- whether the transaction id and ticket id are the same across both events,
- and whether the issue is session-specific or generally reproducible.

## 2. Trace begin-event write conditions

Review the code paths responsible for beginning transaction lifecycle work and verify:

- what preconditions are checked before emitting `tx.begin`,
- whether active non-terminal transactions are rejected,
- whether same-id duplicate begin is blocked,
- whether terminal versus non-terminal history is distinguished correctly.

## 3. Review replay and integrity semantics

Inspect replay/rebuild logic for duplicate-begin handling and clarify:

- what qualifies as a duplicate begin,
- whether the current invalid-event classification is correct,
- how rebuild metadata should represent the failure,
- and whether any current behavior allows partial continuation in a misleading state.

## 4. Review state-capture implications

Determine how invalid replay affects downstream operations such as:

- state capture,
- resume brief generation,
- handoff export,
- and task-summary workflows.

The goal is to preserve strictness without making healthy repository work impossible when only observability/capture paths encounter historical invalidity.

## Proposed 0.5.3 changes

## A. Prevent duplicate `tx.begin` at write time

Transaction-start code should reject any attempt to emit `tx.begin` when doing so would violate canonical lifecycle ordering.

At minimum, begin emission should be blocked when:

- the target transaction is already active and non-terminal,
- the same transaction has already been started and not cleanly resolved,
- or the caller should be using task-update/resume semantics instead of a fresh begin.

This should be treated as a lifecycle contract violation, not a benign duplicate.

## B. Keep replay strict and explicit

Replay should continue to treat malformed lifecycle history as invalid.

If duplicate `tx.begin` is encountered, replay should:

- classify it explicitly,
- preserve enough metadata for diagnosis,
- avoid silently manufacturing a misleading canonical state,
- and report the failure in a way downstream tooling can reason about.

## C. Improve operational follow-up signaling

When invalid history exists, the system should provide clearer guidance about what remains possible.

For example:

- whether normal repository work can continue,
- whether state capture is blocked by integrity policy,
- whether a repair/rebuild step is required,
- and what the recommended operator action is.

The goal is explicit operational behavior, not silent degradation.

## D. Add regression coverage

Regression tests should cover both prevention and detection.

That includes:

- begin-event write guards,
- duplicate-begin replay detection,
- integrity metadata expectations,
- and behavior of state-facing tools when duplicate begin history exists.

## Acceptance criteria

The 0.5.3 work should satisfy all of the following.

### Duplicate-begin prevention
- Normal task-start flows do not emit duplicate `tx.begin` for an already-started non-terminal transaction.
- Same-transaction duplicate begin attempts are rejected with a clear error or failure result.
- Resume/progress flows no longer re-enter the lifecycle through an invalid begin path.

### Replay and integrity correctness
- Replay detects duplicate `tx.begin` deterministically.
- Duplicate begin remains an explicit integrity failure rather than being silently treated as valid history.
- Rebuild metadata captures the invalid event and failure reason clearly.

### Operational clarity
- State-oriented tooling surfaces actionable guidance when invalid transaction history blocks canonical capture.
- The system does not pretend that invalid replay is healthy.
- Error handling distinguishes between uninitialized logs, empty valid logs, and malformed/invalid lifecycle history.

### Regression protection
- Tests fail if begin-event guards regress and allow duplicate lifecycle starts.
- Tests fail if replay stops surfacing duplicate begin as an integrity issue.
- Tests cover the expected behavior of state/rebuild flows in the presence of duplicate-begin history.

## Design principles

## 1. Preserve strict resumability guarantees

The event log is canonical. Fixes should strengthen, not weaken, confidence in replayed state.

## 2. Prevent invalid history earlier

It is better to reject an invalid begin write than to let it enter the log and fail later during replay.

## 3. Prefer explicit failure over silent recovery

If the log is invalid, the system should say so clearly rather than inventing a misleading “best effort” state.

## 4. Separate prevention from remediation

The release should address both:

- how invalid duplicate begin events are prevented going forward,
- and how the system behaves when historical invalid data already exists.

## Candidate implementation areas

The following areas are likely relevant to the 0.5.3 fix:

- transaction lifecycle start helpers,
- task lifecycle wrappers that may emit `tx.begin`,
- replay/state rebuild logic,
- state capture and observability helpers,
- tests around lifecycle ordering and invalid-event handling.

Exact file-level scope should be confirmed during implementation.

## Test impact

The fix should be accompanied by focused regression coverage, including tests for:

1. rejecting duplicate begin emission for an active transaction,
2. replay classification of duplicate `tx.begin` as invalid,
3. preserved integrity metadata for diagnostic purposes,
4. state-capture or summary-path behavior when duplicate begin exists,
5. normal begin flows continuing to work after the guard changes.

## Risks

### Medium behavioral risk
Tightening begin guards may expose latent caller bugs that previously passed unnoticed.

**Mitigation**
- Keep the validation rules explicit.
- Update callers that were relying on invalid restart behavior.
- Add regression coverage for legitimate resume/update flows.

### Medium recovery-path risk
Historical logs that already contain duplicate begin events may continue to trigger integrity failures until explicitly handled.

**Mitigation**
- Preserve strong diagnostics.
- Make operator guidance explicit.
- Distinguish clearly between prevention of new invalid events and remediation of old invalid history.

### Low model risk
This work should not require changes to the broader transaction-state model.

**Mitigation**
- Keep the fix focused on begin-event integrity, replay correctness, and operational clarity.
- Avoid unrelated lifecycle refactors.

## Validation plan

After implementation, validation should include:

1. verifying that duplicate `tx.begin` can no longer be emitted through normal start/resume flows,
2. verifying that replay still flags historical duplicate begin as invalid,
3. verifying that integrity metadata is preserved and understandable,
4. verifying that state-facing tools produce clear outcomes under invalid-history conditions,
5. verifying that normal transaction start, verify, commit, and end flows still work correctly.

## Expected outcome

After 0.5.3:

- transaction-log integrity should be more robust,
- duplicate lifecycle starts should be prevented,
- replay/state rebuild should remain strict and diagnosable,
- and the resumability model should be more reliable under interruption and recovery.

## Summary

Version 0.5.3 should focus on investigating and fixing transaction-log drift caused by duplicate `tx.begin`.

The release should:

- identify the source of the duplicate begin event,
- prevent invalid lifecycle-start writes,
- preserve strict replay/integrity behavior,
- improve operational clarity when historical invalidity exists,
- and add regression coverage so the issue does not recur.