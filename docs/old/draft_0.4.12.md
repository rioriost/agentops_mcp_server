# Draft for 0.4.12: tx state synchronization and canonical workflow recovery

## Background
- The current AgentOps workflow relies on two canonical persistence artifacts:
  - `.agent/tx_event_log.jsonl`
  - `.agent/tx_state.json`
- The intended contract is that transaction progress is durable, resumable, and validated through strict ordering rules.
- The workflow also expects task lifecycle operations, verification, and commit operations to observe the same canonical transaction state.
- In recent execution, the repository recorded transaction events successfully, but follow-up lifecycle and commit operations still failed with workflow guard errors.

## Observed failure
The `.agent` logs show a synchronization problem between the canonical event log and the materialized transaction state.

Observed errors included:
- `commit.start requires verify.pass`
- `tx.begin required before other events`
- `verify.start emitted but tx_state was not updated to running`

At the same time, the event log contained later-stage events showing that:
- a planning transaction had already reached `verify.pass`,
- commit events had been appended,
- the transaction had been marked done,
- and a subsequent ticket `tx.begin` had already been emitted.

This means the system recorded event progress, but later checks still evaluated the transaction state as if that progress had not been fully materialized.

## Problem
The current implementation allows a canonical mismatch in which:
1. transaction events are appended to `.agent/tx_event_log.jsonl`,
2. but `.agent/tx_state.json` is not updated consistently enough to reflect the same lifecycle position,
3. and strict workflow guards then reject valid follow-up operations because they rely on stale or incomplete state.

This breaks resumability and undermines the intended canonical ordering contract.

The issue appears in at least these forms:
- `tx.begin` exists in the event log, but task lifecycle operations still think no transaction has begun,
- `verify.start` or `verify.pass` has been emitted, but commit gating still thinks verification is missing,
- the event log and materialized state disagree about the active transaction,
- rebuild or capture flows can leave `last_applied_seq` appearing current while the active transaction payload is inconsistent with the latest event sequence.

## Goal
- Restore strict synchronization between event-log progression and materialized transaction state.
- Ensure every guarded workflow operation observes the same canonical transaction context.
- Make transaction rebuild, verification, commit, and task-lifecycle behavior converge on one consistent source of truth.
- Preserve the existing strict transaction model rather than weakening validation.

## Proposed changes

### 1. Enforce canonical state synchronization after each transaction event
- Ensure event emission and materialized state updates remain coupled.
- After each canonical transaction transition, the materialized state must reflect the new lifecycle position before downstream guarded operations run.
- Specifically ensure synchronization for:
  - `tx.begin`
  - task lifecycle progression
  - `tx.verify.start`
  - `tx.verify.pass`
  - `tx.verify.fail`
  - `tx.commit.start`
  - `tx.commit.done`
  - `tx.commit.fail`
  - `tx.end.done`
  - `tx.end.blocked`

### 2. Prevent event-log / tx-state drift
- Strengthen the contract so `.agent/tx_event_log.jsonl` and `.agent/tx_state.json` cannot silently diverge.
- If event append succeeds but state update does not, the system should surface a clear integrity failure instead of allowing later tools to operate on stale state.
- Avoid situations where `last_applied_seq` suggests the state is current while the active transaction body still reflects an older lifecycle stage or an empty/default state.

### 3. Make guarded operations validate against consistent transaction state
- Ensure task lifecycle operations, verify helpers, and commit helpers all interpret transaction context the same way.
- Eliminate cases where one component accepts a transaction as active while another rejects it as missing, unverified, or not running.
- Make commit gating depend on a synchronized canonical verify state, not on partially updated or ambiguously reconstructed state.

### 4. Clarify active transaction selection during rebuild and resume
- Ensure rebuild logic correctly materializes the most recent active transaction from the event log.
- Ensure `tx.end.*` followed by a new `tx.begin` results in the later transaction becoming the active one.
- Ensure the system does not collapse into a default "no active transaction" state when the event log clearly contains a more recent active transaction.
- Review whether mixed session identifiers affect active transaction reconstruction and guard behavior, and make the handling explicit and deterministic.

### 5. Strengthen failure observability
- Preserve structured failure records in `.agent/errors.jsonl`.
- Ensure synchronization failures are reported with enough detail to identify:
  - expected transaction state,
  - observed transaction state,
  - relevant event sequence,
  - active ticket id,
  - session context,
  - and the workflow guard that rejected the action.
- Prefer explicit integrity diagnostics over indirect downstream failures.

### 6. Add regression protection
- Add tests covering the failure modes observed in 0.4.11 analysis:
  - event log contains `tx.begin` but task lifecycle operations still reject the ticket,
  - verify events exist but commit gating still rejects with missing verify state,
  - rebuild produces a stale or empty active transaction despite later events,
  - `last_applied_seq` advances without the active transaction being updated consistently,
  - active transaction handoff after `tx.end.done` followed by a new `tx.begin`,
  - error logging for synchronization and guard failures.

## Non-goals
- Relaxing canonical workflow rules.
- Allowing commit or lifecycle actions to proceed when state is ambiguous.
- Replacing the transaction log model with a looser best-effort tracking system.
- Introducing separate competing sources of truth for transaction progress.

## Desired outcome
- The canonical event log and materialized transaction state always agree on the active transaction and lifecycle stage.
- Workflow guard errors only occur for real contract violations, not because of stale or partially synchronized state.
- Resume behavior becomes predictable and safe after interruption, rebuild, or guard-triggered recovery.
- Failures become diagnosable from `.agent` artifacts without needing to infer state drift indirectly.

## Acceptance criteria
- A transaction that emits `tx.begin` is recognized as active by subsequent task lifecycle operations.
- A transaction that emits successful verify events is recognized as verified by commit gating.
- Rebuild logic materializes the latest active transaction correctly from the event log.
- `last_applied_seq` cannot indicate a fully applied state while the active transaction content remains inconsistent with the latest events.
- `tx.end.done` followed by a later `tx.begin` results in the later transaction becoming active.
- Synchronization failures are logged clearly enough to diagnose root cause from `.agent/errors.jsonl` and related state artifacts.
- Regression tests cover the observed event-log / state mismatch scenarios.

## Implementation notes
- Prefer fixing the synchronization contract and materialization logic rather than weakening guard checks.
- Treat event append and state persistence as a single canonical progression path.
- If a state update cannot be completed after an event append, fail loudly and preserve integrity information.
- Review rebuild, capture, verify, and commit flows together so they all honor the same active transaction model.

## Verification strategy
- Add targeted tests for transaction rebuild and guard consistency.
- Reproduce the previously observed failure patterns with tests.
- Confirm that task lifecycle, verify, and commit flows behave consistently against synchronized state.
- Verify that `.agent/errors.jsonl` records synchronization failures with actionable context.
- Run repository verification after implementing the fixes.

## Rollout notes
- Keep 0.4.12 focused on canonical state synchronization and workflow integrity.
- Avoid expanding scope into unrelated planning or documentation changes.
- Prioritize resumability, deterministic recovery, and guard correctness.