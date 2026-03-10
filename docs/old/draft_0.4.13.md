# Draft for 0.4.13: transaction state machine hardening and workflow repair

## Background
- Since 0.4.0, the system requires transaction-aware task management.
- A single ticket must be represented as a single transaction from start to terminal completion.
- The canonical workflow depends on:
  - `.agent/tx_event_log.jsonl` as the append-only transaction history
  - `.agent/tx_state.json` as the materialized current transaction state
- Resumability, verification, commit safety, and operator trust all depend on these artifacts remaining consistent.
- Recent failures showed that the system can enter transaction-invalid flows, including lifecycle violations such as:
  - `tx.begin required before other events`
  - `verify.start emitted but tx_state was not updated to running`
  - `commit.start requires verify.pass`
  - `duplicate tx.begin`

## Problem
The current implementation does not yet define the transaction lifecycle as an explicit state machine with required transitions, forbidden transitions, and recovery behavior.

As a result:
- different components can interpret the active transaction differently,
- resume logic can behave like new-start logic,
- guarded operations can observe stale or incomplete materialized state,
- event emission can proceed into flows that later fail invariant checks,
- and invalid transaction sequences can be recorded before the system stops.

This violates the 0.4.0 requirement that a ticket must be managed correctly as one coherent transaction from start through completion, without inconsistency during execution.

## Goal
- Define the transaction lifecycle as an explicit state machine.
- Make valid transitions and invalid transitions unambiguous.
- Require detection of workflow paths that violate the transaction model.
- Define implementation changes needed to prevent, detect, and repair such violations.
- Preserve strict correctness rather than relaxing guards.

## Canonical model

### Core identity
- One ticket corresponds to one active transaction lineage at a time.
- A transaction is identified by `tx_id` and associated `ticket_id`.
- A non-terminal transaction must remain uniquely identifiable until it reaches a terminal state.
- Resume must continue the same transaction lineage, not create a second begin for the same non-terminal work.

### Canonical artifacts
- `.agent/tx_event_log.jsonl` is the canonical ordered event history.
- `.agent/tx_state.json` is the canonical materialized view derived from that history and must remain synchronized with it.
- If the event log and materialized state disagree, the system must treat that as an integrity failure, not as a normal recoverable success path.

## Transaction state machine

### Transaction statuses
The transaction lifecycle uses these statuses:

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

### Transaction phases
- `planned`: transaction not yet begun, or default empty state
- `in-progress`: work is actively underway
- `checking`: implementation is complete and verification is pending or being evaluated
- `verified`: verification has passed
- `committed`: commit has completed successfully
- `done`: terminal success
- `blocked`: terminal non-success halt

### Verification sub-state
Verification state must be tracked explicitly:

- `not_started`
- `running`
- `passed`
- `failed`

### Commit sub-state
Commit state must be tracked explicitly:

- `not_started`
- `running`
- `passed`
- `failed`

## Required lifecycle transitions

### Valid top-level flow
The canonical happy path for one ticket is:

1. `planned`
2. `tx.begin`
3. `in-progress`
4. implementation / file intent progression
5. `checking`
6. `tx.verify.start`
7. `tx.verify.pass`
8. `verified`
9. `tx.commit.start`
10. `tx.commit.done`
11. `committed`
12. `tx.end.done`
13. `done`

### Valid blocked flow
A blocked path is:

1. `planned`
2. `tx.begin`
3. `in-progress`
4. implementation or diagnostic work
5. `tx.end.blocked`
6. `blocked`

### Valid verification retry flow
A verify-retry path is:

1. `in-progress`
2. `checking`
3. `tx.verify.start`
4. `tx.verify.fail`
5. return to fix work
6. `in-progress`
7. `checking`
8. `tx.verify.start`
9. `tx.verify.pass`
10. `verified`

### Valid resume flow
A resume path must satisfy all of the following:
- the transaction already has a prior `tx.begin`,
- the transaction is not terminal,
- resume does not emit another `tx.begin`,
- resume restores the active transaction context from canonical state,
- subsequent task lifecycle events continue the existing transaction.

## Forbidden transitions and invariant violations

The following are specification violations and must be detected explicitly:

### 1. Lifecycle before begin
Examples:
- `ops_start_task` or equivalent lifecycle progression without prior `tx.begin`
- status update for an active ticket when no begin exists in canonical history

This must fail with an integrity error.

### 2. Duplicate begin on a non-terminal transaction
Examples:
- emitting `tx.begin` twice for the same non-terminal transaction
- treating resume as new work start
- starting a new active transaction for the same ticket when the prior one is still open

This must fail with an integrity error.

### 3. Verify result without verify start
Examples:
- `tx.verify.pass` without `tx.verify.start`
- `tx.verify.fail` without `tx.verify.start`

This must fail with an integrity error.

### 4. Commit start without successful verify
Examples:
- `tx.commit.start` before `tx.verify.pass`
- commit helper deciding that verify succeeded based on stale state rather than canonical synchronized state

This must fail with an integrity error.

### 5. Materialized state lag after event append
Examples:
- `tx.verify.start` recorded in the event log, but `tx_state` still shows `verify_state.status = not_started`
- `tx.verify.pass` recorded, but commit gating still sees unverified state
- `tx.begin` recorded, but task lifecycle helpers still behave as if no transaction exists

This must fail as synchronization drift.

### 6. Active transaction loss
Examples:
- event history shows a non-terminal transaction, but rebuilt or materialized state collapses to `none`
- latest active transaction is not selected deterministically after replay

This must fail as active-transaction reconstruction drift.

### 7. Event after terminal state
Examples:
- appending lifecycle, verify, or commit events after `tx.end.done`
- appending lifecycle, verify, or commit events after `tx.end.blocked`

This must fail with an integrity error.

## Required operational semantics

### Begin semantics
- `tx.begin` may be emitted only when there is no matching non-terminal transaction already active for the same ticket.
- begin must atomically establish:
  - `tx_id`
  - `ticket_id`
  - `status`
  - `phase`
  - `current_step`
  - `session_id`
  - initial verify state
  - initial commit state
  - next action
  - semantic summary

### Resume semantics
- resume must first reconstruct canonical active transaction context.
- if a non-terminal transaction exists, resume must bind to it.
- resume must not emit `tx.begin`.
- if canonical state is ambiguous, the system must stop in a diagnostic failure path rather than guessing.

### Verify semantics
- `tx.verify.start` requires:
  - a valid active transaction,
  - all required file intents for the current step to be in the applied state,
  - synchronized materialized state before downstream verification result handling.
- `tx.verify.pass` requires a prior verify start for the same step.
- `tx.verify.fail` requires a prior verify start for the same step.

### Commit semantics
- `tx.commit.start` requires:
  - a valid active transaction,
  - a synchronized verified state,
  - a canonical prior `tx.verify.pass`.
- commit must not infer success from local assumptions if the canonical state does not confirm verification.
- `tx.commit.done` and `tx.commit.fail` require a prior `tx.commit.start`.

### End semantics
- `tx.end.done` requires a logically completed transaction.
- `tx.end.blocked` requires an explicit blocked outcome.
- after either terminal event, the transaction must no longer accept non-terminal follow-up events.

## Required synchronization rules

### Event/state coupling
For any canonical transaction event:
1. validate preconditions,
2. append event,
3. update materialized state to reflect the new canonical position,
4. expose the updated state to downstream guarded operations.

The system must not allow this sequence:
1. append event succeeds,
2. state update does not reflect that event,
3. downstream logic runs against stale state.

### Canonical read behavior
All guarded operations must observe transaction context through the same canonical interpretation.
This means:
- task lifecycle helpers,
- verify helpers,
- commit helpers,
- rebuild flows,
- handoff/capture flows

must agree on:
- active transaction identity,
- current phase/status,
- verify state,
- commit state,
- next action.

### Drift handling
If event append and state materialization diverge:
- the system must surface an integrity failure,
- the failure must be logged with actionable context,
- the system must stop the invalid workflow progression,
- and it must not continue by silently defaulting to an empty or guessed state.

## Repair strategy for the observed specification violations

### 1. Make the state machine explicit in code
Implement the transaction lifecycle as explicit allowed transitions rather than distributed assumptions.

Required outcomes:
- one place defines valid transitions,
- one place defines forbidden transitions,
- all helpers use the same transition rules,
- invalid flows fail before mutating canonical state further.

### 2. Separate new-start from resume decisively
Repair start/resume control flow so that:
- new start emits `tx.begin`,
- resume reuses the existing non-terminal transaction,
- no helper emits `tx.begin` merely because materialized state looks incomplete,
- no helper converts reconstruction uncertainty into a new transaction begin.

### 3. Enforce synchronized state after every canonical event
Repair event emission paths so that after:
- `tx.begin`
- lifecycle updates
- `tx.verify.start`
- `tx.verify.pass`
- `tx.verify.fail`
- `tx.commit.start`
- `tx.commit.done`
- `tx.commit.fail`
- `tx.end.done`
- `tx.end.blocked`

the materialized transaction state reflects the same lifecycle position before any guarded follow-up logic runs.

### 4. Make rebuild authoritative for integrity, not permissive
Repair rebuild behavior so that it:
- deterministically identifies the latest active non-terminal transaction,
- rejects invalid sequences such as duplicate non-terminal begin,
- preserves enough context to diagnose the invalid event and prior event sequence,
- does not silently degrade to a default empty active state when canonical history indicates otherwise.

### 5. Stop invalid follow-up work immediately on integrity failure
When a violation is detected:
- do not continue with verify,
- do not continue with commit,
- do not continue with lifecycle progression,
- do not try to self-heal by issuing another begin,
- return a direct integrity failure with transaction context.

### 6. Improve diagnostics for workflow violations
For each integrity failure, record enough detail to identify:
- active transaction id
- ticket id
- expected next action
- actual attempted action
- last applied sequence
- invalid event sequence number if applicable
- verify state
- commit state
- session context
- whether the failure came from stale materialized state or invalid event ordering

### 7. Add regression tests for every forbidden flow
Add tests that cover at minimum:

- lifecycle action before `tx.begin`
- duplicate `tx.begin` on a non-terminal transaction
- verify result without verify start
- commit start without verify pass
- event/state divergence after verify start
- event/state divergence after verify pass
- active transaction lost during rebuild
- post-terminal event rejection
- resume binding to existing transaction instead of creating a new begin
- repeated recovery attempts not multiplying the same invalid sequence

## Scope of fixes for 0.4.13
0.4.13 should focus on transaction correctness and repair of specification-violating flows.

Included:
- explicit transaction state machine definition
- detection of invalid lifecycle transitions
- prevention of duplicate non-terminal begin
- synchronized event/state progression
- canonical active transaction reconstruction
- improved integrity diagnostics
- regression coverage for observed workflow failures

Excluded:
- weakening validation rules
- broad redesign of planning artifacts
- introducing alternate sources of truth for transaction progress
- best-effort continuation when transaction correctness is ambiguous

## Acceptance criteria

### State machine correctness
- The transaction lifecycle is documented as an explicit state machine.
- Valid transitions and forbidden transitions are clearly defined.
- Resume is specified separately from new transaction start.

### Runtime correctness
- A non-terminal transaction cannot receive a second `tx.begin`.
- A lifecycle operation cannot proceed before `tx.begin`.
- A commit cannot start before canonical verify pass.
- A verify result cannot be recorded without canonical verify start.
- A terminal transaction cannot accept additional non-terminal events.

### Synchronization correctness
- After any canonical event append, the materialized state reflects the same lifecycle position before downstream guarded logic executes.
- Guarded operations do not disagree about whether a transaction exists, is running, is verified, or is committed.
- Rebuild deterministically materializes the correct active transaction or fails with a specific integrity error.

### Observability correctness
- Integrity failures include actionable transaction context.
- Drift between event log and materialized state is surfaced directly.
- Repeated invalid flows are diagnosable from `.agent` artifacts.

### Regression coverage
- Tests reproduce and lock the previously observed invalid flows.
- Tests confirm that invalid sequences are rejected early and do not cascade into misleading later failures.

## Desired outcome
- Every ticket is managed as one coherent transaction from start to terminal completion.
- The system no longer permits transaction-invalid flows during execution.
- Resume behavior is deterministic and safe.
- Guard errors correspond to real specification violations, not stale or ambiguous state.
- Canonical transaction management in 0.4.x matches the 0.4.0 requirement for correct transaction-aware task execution.