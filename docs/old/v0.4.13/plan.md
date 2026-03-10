# Implementation Plan: 0.4.13 Transaction state machine hardening and workflow repair

## Objectives
- Define and enforce the transaction lifecycle as an explicit state machine.
- Prevent transaction-invalid execution paths during ticket processing.
- Ensure one ticket is managed as one coherent transaction from start to terminal completion.
- Detect and stop specification-violating flows before they cascade into secondary guard failures.
- Restore strict consistency between canonical transaction history and materialized transaction state.
- Improve diagnostics and regression coverage for transaction integrity failures.

## Background
Since 0.4.0, the system requires transaction-aware task management.

That means:
- one ticket corresponds to one transaction lineage,
- a non-terminal transaction must remain uniquely identifiable throughout execution,
- resume must continue an existing non-terminal transaction rather than creating a new begin,
- and task lifecycle, verify, commit, rebuild, and recovery behavior must all agree on the same canonical transaction context.

Recent failures show that transaction-invalid flows are still possible, including:
- `tx.begin required before other events`
- `verify.start emitted but tx_state was not updated to running`
- `commit.start requires verify.pass`
- `duplicate tx.begin`

These failures indicate that the current implementation still permits lifecycle violations, synchronization drift, or ambiguous recovery behavior.

## Problem Statement
The implementation does not yet fully encode the transaction model as one explicit state machine with:
- allowed transitions,
- forbidden transitions,
- shared precondition checks,
- deterministic resume rules,
- and strict handling of integrity failures.

As a result, the system can:
1. treat resume as a new start and emit a duplicate `tx.begin`,
2. allow helpers to disagree about whether a transaction exists or is active,
3. append canonical events that are not reflected in materialized state before follow-up logic runs,
4. attempt verify or commit progression against stale transaction state,
5. lose the active transaction during rebuild or recovery,
6. and produce downstream guard errors that hide the earlier specification violation.

This release should repair those paths and make transaction-invalid execution structurally impossible or explicitly rejected.

## Scope

### In scope
- Explicit transaction state machine definition in implementation-facing artifacts
- Enforcement of allowed and forbidden transaction transitions
- Strict separation of new-start and resume behavior
- Prevention of duplicate non-terminal `tx.begin`
- Synchronization between canonical event progression and materialized transaction state
- Deterministic active transaction reconstruction during rebuild and resume
- Integrity-failure handling and diagnostics for specification-violating flows
- Regression coverage for all observed transaction-invalid paths

### Out of scope
- Weakening validation rules
- Best-effort continuation when canonical transaction state is ambiguous
- Broad redesign of planning artifacts unrelated to transaction correctness
- Replacing the canonical event-log model
- Introducing alternate sources of truth for transaction progress

## Phases

### Phase 1: Codify the transaction state machine and invariants
**Goals**
- Translate the 0.4.13 draft into implementation-facing rules.
- Make the lifecycle contract explicit enough that all runtime helpers can share it.
- Define the exact conditions that constitute transaction integrity failures.

**Tasks**
- Define the canonical transaction lifecycle in implementation terms:
  - `planned`
  - `in-progress`
  - `checking`
  - `verified`
  - `committed`
  - `done`
  - `blocked`
- Define verification sub-state requirements:
  - `not_started`
  - `running`
  - `passed`
  - `failed`
- Define commit sub-state requirements:
  - `not_started`
  - `running`
  - `passed`
  - `failed`
- Define allowed transitions for:
  - begin
  - lifecycle progression
  - verify start/result
  - commit start/result
  - terminal end
  - resume
- Define forbidden transitions, including:
  - lifecycle before begin
  - duplicate non-terminal begin
  - verify result without verify start
  - commit start without verify pass
  - post-terminal non-terminal events
  - active transaction loss despite canonical non-terminal history
  - event/state divergence after canonical progression
- Define the exact failure boundary between:
  - recoverable operational failure,
  - synchronization drift,
  - and transaction integrity failure.
- Define how canonical state should be interpreted when materialized state is stale, incomplete, or defaulted.

**Deliverables**
- Explicit implementation contract for transaction lifecycle rules
- Explicit invariant list for begin/resume/verify/commit/end behavior
- Explicit classification of specification-violating flows and required failure behavior

---

### Phase 2: Repair start, resume, and active-transaction selection
**Goals**
- Ensure the system never confuses resume with new transaction start.
- Ensure active transaction identity remains stable throughout a ticket's lifecycle.
- Prevent duplicate `tx.begin` on non-terminal work.

**Tasks**
- Review current start and resume control flow for all task lifecycle helpers.
- Ensure new-start logic emits `tx.begin` only when no matching non-terminal transaction already exists.
- Ensure resume logic:
  - reconstructs canonical active transaction context first,
  - binds to the existing non-terminal transaction,
  - and does not emit another `tx.begin`.
- Ensure ambiguity in canonical transaction reconstruction causes an explicit integrity failure instead of a guessed restart.
- Ensure helpers do not fall back to "no active transaction" when canonical history shows an unfinished one.
- Ensure task lifecycle operations derive transaction identity from a shared canonical interpretation rather than helper-local assumptions.

**Deliverables**
- Repaired start/resume behavior
- Stable active transaction binding across task lifecycle helpers
- Prevention of duplicate begin for non-terminal transactions

---

### Phase 3: Enforce synchronized canonical progression for begin, verify, commit, and end
**Goals**
- Ensure canonical event progression and materialized transaction state remain coupled at every lifecycle step.
- Prevent downstream guarded operations from observing stale state after a successful event append.
- Ensure commit gating and verify gating operate on the same canonical view.

**Tasks**
- Review event emission paths for:
  - `tx.begin`
  - task lifecycle updates
  - `tx.verify.start`
  - `tx.verify.pass`
  - `tx.verify.fail`
  - `tx.commit.start`
  - `tx.commit.done`
  - `tx.commit.fail`
  - `tx.end.done`
  - `tx.end.blocked`
- Ensure each canonical progression step follows this rule:
  1. validate preconditions,
  2. append canonical event,
  3. materialize the same lifecycle position into transaction state,
  4. expose only the synchronized state to downstream guards.
- Prevent flows where:
  - begin exists in canonical history but lifecycle helpers still reject follow-up actions,
  - verify start exists but verify state remains `not_started`,
  - verify pass exists but commit gating still sees unverified state,
  - last applied sequence advances while active transaction payload remains stale.
- Ensure terminal events close the transaction definitively for later guard evaluation.
- Ensure non-terminal follow-up events after terminal state are rejected early and explicitly.

**Deliverables**
- Repaired synchronized progression for begin/verify/commit/end
- Guard behavior aligned with canonical synchronized state
- Elimination of stale-state follow-up failures caused by incomplete materialization

---

### Phase 4: Harden rebuild, capture, and recovery against transaction-invalid flows
**Goals**
- Make rebuild authoritative for transaction integrity and active-transaction reconstruction.
- Ensure recovery behavior is deterministic and does not silently collapse into empty state.
- Prevent invalid history from being treated as a valid base for continued work.

**Tasks**
- Review replay and rebuild logic for transaction identity tracking and terminal handoff behavior.
- Ensure rebuild:
  - deterministically identifies the latest active non-terminal transaction,
  - rejects invalid sequences such as duplicate non-terminal begin,
  - preserves enough context to diagnose invalid history,
  - and does not silently downgrade to default empty state when canonical history contradicts that result.
- Ensure terminal handoff works correctly when:
  - `tx.end.done` is followed by a later `tx.begin`
  - `tx.end.blocked` is followed by a later `tx.begin`
- Ensure capture/recovery flows do not overwrite valid active transaction state with a default `none` transaction unless canonical replay truly yields that result.
- Define deterministic behavior when multiple sessions appear in the same canonical history.

**Deliverables**
- Hardened rebuild and recovery behavior
- Deterministic active-transaction reconstruction
- Clear integrity-failure handling for invalid event sequences

---

### Phase 5: Improve observability and diagnostics for integrity failures
**Goals**
- Make transaction-invalid flows diagnosable directly from runtime artifacts.
- Ensure earlier integrity failures are visible instead of being hidden behind later guard failures.
- Improve operator understanding of expected versus observed transaction state.

**Tasks**
- Improve structured error reporting for:
  - duplicate begin
  - missing begin
  - verify result without verify start
  - commit start without verify pass
  - event/state divergence
  - active transaction reconstruction failure
  - post-terminal event attempts
- Ensure integrity diagnostics include enough context to identify:
  - active transaction id
  - ticket id
  - expected next action
  - attempted action
  - last applied sequence
  - invalid event sequence if available
  - transaction status/phase
  - verify state
  - commit state
  - session context
  - validation point
  - whether failure came from invalid ordering or synchronization drift
- Ensure repeated failures are still diagnosable as the same root violation rather than appearing as unrelated secondary errors.
- Ensure transaction-integrity diagnostics distinguish:
  - invalid canonical sequence,
  - stale materialized state,
  - and ambiguous recovery state.

**Deliverables**
- Better integrity diagnostics in `.agent` artifacts
- Clearer failure records for transaction-invalid execution paths
- Improved operator-facing diagnosis of root-cause transaction failures

---

### Phase 6: Add regression coverage for forbidden flows and repair guarantees
**Goals**
- Lock the repaired transaction model with automated checks.
- Ensure every observed invalid flow is reproducible and prevented.
- Ensure fixes do not regress under rebuild, recovery, or guarded execution.

**Tasks**
- Add or extend tests covering:
  - lifecycle action before `tx.begin`
  - duplicate `tx.begin` on a non-terminal transaction
  - verify result without prior verify start
  - commit start without canonical verify pass
  - event/state drift after `tx.begin`
  - event/state drift after `tx.verify.start`
  - event/state drift after `tx.verify.pass`
  - active transaction loss during rebuild
  - correct active handoff after terminal event followed by a later begin
  - rejection of post-terminal non-terminal events
  - resume binding to existing non-terminal transaction rather than creating a new begin
  - repeated recovery attempts not multiplying the same invalid flow
  - integrity diagnostics being written with actionable context
- Add checks that task lifecycle, verify, commit, rebuild, and capture paths all evaluate the same canonical transaction context.
- Run repository verification and targeted regression tests.

**Deliverables**
- Regression tests covering forbidden transaction flows
- Verification evidence that repaired state-machine behavior is enforced
- Automated protection against recurrence of the observed transaction-invalid paths

## Acceptance Criteria

### State machine correctness
- The transaction lifecycle is documented and implemented as an explicit state machine.
- Allowed transitions and forbidden transitions are defined clearly enough to drive runtime checks.
- Resume behavior is specified and implemented separately from new transaction start.

### Runtime correctness
- A non-terminal transaction cannot receive a second `tx.begin`.
- Lifecycle operations cannot proceed before canonical begin.
- Verify results cannot be recorded without canonical verify start.
- Commit cannot start before canonical verify pass.
- Terminal transactions cannot accept additional non-terminal events.
- Invalid transaction flows are rejected directly instead of cascading into misleading later failures.

### Synchronization correctness
- After any canonical event append, materialized transaction state reflects the same lifecycle position before downstream guarded logic runs.
- Task lifecycle, verify, commit, rebuild, and recovery helpers do not disagree about whether a transaction exists, is active, is verified, or is committed.
- `last_applied_seq` cannot advance while `active_tx` remains stale, empty, or inconsistent with the latest canonical events.
- Canonical transaction state does not silently collapse to a default empty transaction when replay still shows a valid non-terminal active transaction.

### Recovery correctness
- Rebuild deterministically materializes the correct active transaction or fails with a specific integrity error.
- Resume binds to the existing canonical non-terminal transaction rather than creating a second begin.
- Terminal handoff to a later begin is handled deterministically.

### Observability correctness
- Integrity failures include enough context to identify the violated invariant and affected transaction.
- Drift between canonical events and materialized state is surfaced directly.
- Repeated invalid flows remain diagnosable as one root integrity problem.

### Regression coverage
- Tests reproduce the previously observed invalid flows.
- Tests verify that invalid sequences are rejected early and do not continue into misleading secondary errors.
- Repository verification passes with the repaired transaction model in place.

## Risks and Mitigations
- **Risk:** Fixes may treat symptoms at individual guards without enforcing a shared lifecycle model.  
  **Mitigation:** Make the explicit state machine and invariants the primary implementation contract, then align all helpers to it.

- **Risk:** Resume and rebuild logic may still derive active transaction identity differently across components.  
  **Mitigation:** Centralize canonical active-transaction interpretation and test cross-component consistency.

- **Risk:** Event append and state materialization may still drift during edge cases.  
  **Mitigation:** Require synchronized progression after every canonical event and add tests for each lifecycle boundary.

- **Risk:** Rebuild may still degrade invalid or ambiguous history into a misleading default state.  
  **Mitigation:** Treat ambiguity and invalid sequences as integrity failures, not as successful empty-state recovery.

- **Risk:** Better diagnostics may still emphasize downstream guard failures over root-cause violations.  
  **Mitigation:** Record the first violated invariant and include validation point, transaction context, and event sequence details.

## Verification Strategy
- Add targeted tests for begin, resume, verify, commit, terminal, rebuild, and recovery behavior.
- Reproduce the observed specification-violating flows with automated regression tests.
- Confirm that repaired flows reject invalid transitions before follow-up logic proceeds.
- Confirm that canonical event history and materialized transaction state remain aligned throughout lifecycle progression.
- Confirm that integrity failures are recorded with actionable context.
- Run repository verification after implementation.

## Rollout Notes
- Keep 0.4.13 focused on transaction correctness and repair of specification-violating flows.
- Prefer structural fixes that enforce the transaction model over local patches that suppress symptoms.
- Treat one-ticket/one-transaction coherence as the primary release outcome.
- Do not weaken strict validation to make invalid flows appear successful.