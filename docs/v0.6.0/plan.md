# Implementation Plan: 0.6.0 Redesign the work loop as a resumable transactional protocol

## Objectives
- Redefine the canonical meaning of a transaction in this project as a durable execution attempt for completing one ticket.
- Make the work loop explicitly resumable across MCP server interruption without requiring heuristic recovery.
- Simplify the canonical runtime model so resume decisions depend on a small, explicit state machine.
- Preserve strict lifecycle ordering while reducing identity and recovery ambiguity.
- Keep the canonical persistence model minimal:
  - materialized transaction state
  - append-only transaction event history
  - transaction ID issuance metadata
- Separate planning identity from runtime execution identity:
  - `ticket_id` remains a client-managed work-item label
  - `tx_id` becomes the server-managed durable execution identifier
- Preserve `seq` as the canonical append order for transaction events.
- Make `next_action` sufficient for deterministic continuation of interrupted work.
- Keep repository commit distinct from terminal transaction completion.
- Preserve compatibility for historical logs without requiring in-place rewrite.
- Preserve bounded compatibility for terminal materialized snapshots and post-terminal active-slot clearing shapes without reinterpreting them as replacement lifecycle events.

## Background
The current system already treats tickets as the only unit of work and requires agents to resume a non-terminal active transaction before starting new work.

That is the correct direction, but the current design still mixes several concerns that should be simpler and more explicit:
- planning identity
- execution identity
- current state
- event history
- lifecycle checkpointing
- resume behavior
- commit completion
- terminal completion

As a result, some runtime behavior is harder to reason about than it should be:
- the meaning of `tx_id` is not consistently constrained
- some logic still depends on string-shape assumptions or sentinel values
- begin versus resume behavior is not defined as a compact protocol first
- commit success and task completion are distinct, but that distinction is not yet the organizing principle of the design
- recovery can become more artifact-driven than transaction-protocol-driven

The key issue is not only identifier design.

The deeper issue is that the work loop itself should be modeled as a **resumable transaction protocol** whose purpose is to complete a ticket despite interruption.

## Problem Statement
In this project, a transaction is not primarily a database-style ACID unit over rows.

Instead, it is a **durable unit of work execution** whose purpose is:
- start work on a ticket
- record progress durably
- survive interruption
- resume deterministically
- verify safely
- commit if appropriate
- terminate explicitly as `done` or `blocked`

The current model does not yet make that protocol simple enough.

Today, several concerns are too tightly coupled:
- `ticket_id` and `tx_id`
- runtime state and replay inference
- session context and transaction correctness
- commit completion and terminal success
- event history and current resumable checkpoint

That creates avoidable complexity in:
- begin/resume decisions
- active transaction selection
- interrupted verify/commit continuation
- no-active-transaction representation
- compatibility handling
- implementation and test design

## Core Design Goal
Version `0.6.0` should redefine the work loop so that it behaves like a **true resumable transaction protocol for ticket completion**.

After `0.6.0`, the canonical model should make the following true:

1. A transaction is one durable execution attempt for one ticket.
2. A workspace may have at most one non-terminal active transaction at a time.
3. Resume always targets the exact active transaction, not a heuristically reconstructed replacement.
4. Current resumable state is explicit and materialized.
5. Event history remains append-only and authoritative for rebuild and audit.
6. `next_action` is the primary machine-readable continuation guide.
7. Repository commit is not terminal success by itself.
8. Terminal completion is explicit and remains separate from commit.
9. Recovery uses exact transaction state and exact identifiers rather than string-shape heuristics.
10. Planning artifacts remain client-managed and derived from, not authoritative over, runtime transaction state.

## Canonical Runtime Model

## 1. Ticket
A `ticket_id` identifies a planned work item.

### Role
- planning identity
- client-managed workflow label
- input to transaction creation
- useful for human and planning-tool coordination

### Non-role
A `ticket_id` is not the canonical identity of a running transaction.

A single `ticket_id` may have:
- zero transactions
- one active transaction
- multiple historical transactions over time

## 2. Transaction
A `tx_id` identifies one concrete durable execution attempt.

### Role
A transaction is the canonical unit of resumable work.

It represents:
- work started for one ticket
- current execution phase
- current resumable checkpoint
- current next required action
- the active runtime unit that must be resumed before new work begins

### Important consequences
- `tx_id` is server-managed
- `tx_id` is exact and opaque once issued
- `tx_id` is never derived from `ticket_id`
- the active transaction is the only canonical resumable work item in the workspace
- resume must continue the same `tx_id`, not mint a replacement

## 3. Event
An event is one append-only transaction-history record.

### Role
Events provide:
- audit history
- rebuild input
- integrity trace
- checkpoint chronology

### Ordering
`seq` remains the canonical global append order for events.

## 4. Session
`session_id` may remain available as runtime context, but it should not be the primary organizing concept for correctness in `0.6.0`.

### Role
- observability
- correlation
- handoff continuity
- runtime context when useful

### Bounded role
Transaction correctness and resumability should not depend primarily on session-parent modeling.

For `0.6.0`, the design should prioritize:
- active transaction correctness
- explicit transaction state
- deterministic continuation

over a more elaborate session hierarchy.

## Transaction Semantics

## 1. Transaction meaning
A transaction is not “a batch of row updates”.

A transaction is:
- a durable ticket-scoped work attempt
- a resumable execution context
- a protocol instance that moves through explicit lifecycle checkpoints until terminal completion

## 2. Transaction success
Transaction success is not:
- “verify passed”
- or “commit succeeded”

Transaction success is:
- explicit terminal completion as `done`

This preserves the rule that repository state and lifecycle state are related but distinct.

## 3. Transaction failure / non-success
A transaction may end as:
- `blocked`
- or remain non-terminal until resumed

A failed verify or failed commit does not necessarily terminate the transaction.
It may simply move the transaction into a resumable state that requires further action.

## Canonical Invariants

## 1. Single active transaction
At most one non-terminal active transaction may exist in a workspace.

### Required behavior
- if a non-terminal active transaction exists, it must be resumed first
- no new ticket work may begin while that transaction remains non-terminal
- terminal states are `done` and `blocked`

## 2. Begin creates, resume reuses
A new `tx_id` may be created only when starting a new transaction.

Resume must:
- reuse the existing `tx_id`
- preserve the existing transaction identity
- preserve the existing lifecycle context
- never mint a substitute ID

## 3. Commit is non-terminal
A successful repository commit does not complete the transaction by itself.

After commit, the transaction remains in a non-terminal `committed` state until explicitly ended.

## 4. Terminal completion is explicit
Terminal success requires an explicit terminal transition such as:
- `tx.end.done`

Terminal blocked completion requires:
- `tx.end.blocked`

## 5. Resume is deterministic
Resuming an interrupted transaction should depend on:
- canonical materialized transaction state
- the top-level continuation surface in materialized state:
  - `status`
  - `phase`
  - `next_action`
  - `terminal`
  - `semantic_summary`
  - `verify_state`
  - `commit_state`
- canonical event history when rebuild is needed
- exact active transaction identity

Resume should not depend on:
- string-shape assumptions
- sentinel transaction identifiers
- timestamp-first selection
- planning-document status as a source of truth

## 6. Planning artifacts are derived
Files under `docs/` are useful planning artifacts, but they are not canonical runtime state.

When maintained, they should align with runtime progress, but resume and lifecycle decisions must use canonical transaction state and canonical event history.

## Canonical State Machine

## Status set
The canonical transaction status model should remain intentionally small:

- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

## Meaning of each status

### `in-progress`
The transaction has started and implementation work or repair work is still ongoing.

Typical next action:
- `tx.verify.start`

### `checking`
The transaction is being evaluated against verification or acceptance expectations.

Typical next action:
- continue verification flow
- or resume required checking work

### `verified`
Verification has succeeded for the current transaction state.

Typical next action:
- commit if repository changes exist
- otherwise proceed toward explicit terminal completion if policy allows

### `committed`
Repository commit has completed successfully, but the lifecycle is still non-terminal.

Typical next action:
- `tx.end.done`

### `done`
Terminal successful completion.

Typical next action:
- none

### `blocked`
Terminal blocked completion.

Typical next action:
- none

## State-machine constraints
The protocol should preserve a strict and limited transition model.

Expected high-level flow:
1. `in-progress`
2. `checking`
3. `verified`
4. `committed`
5. `done`

Repair loops may move execution back into resumable non-terminal work before returning to verification.

A blocked path ends as:
- `blocked`

## Canonical Checkpoints and Events
The event model should be organized around resumable checkpoints, not unnecessary detail.

Recommended core checkpoint events:

- `tx.begin`
- `tx.step.enter`
- `tx.verify.start`
- `tx.verify.pass`
- `tx.verify.fail`
- `tx.commit.start`
- `tx.commit.done`
- `tx.commit.fail`
- `tx.end.done`
- `tx.end.blocked`

`tx.step.enter` is the canonical progress-checkpoint event for the 0.6.0 state-machine contract.
Additional events such as file-intent activity may still exist, but the resumable protocol should be understandable primarily from checkpoint events and current materialized state.

## Persistence Model

## 1. Materialized state
Retain canonical materialized state under `.agent/tx_state.json`.

### Purpose
This is the canonical resume entrypoint.

It should capture at least:
- `active_tx`, which is `null` when no active transaction exists
- top-level current status
- top-level current phase
- top-level `next_action`
- top-level terminal flag
- top-level semantic summary
- top-level verification checkpoint state
- top-level commit checkpoint state
- current integrity / workflow guidance fields needed for continuation
- active transaction identity and local checkpoint context when `active_tx` is non-null

### Role
- first source for resume
- machine-readable continuation state
- current canonical view of the active transaction
- holder of the top-level continuation contract for `status`, `phase`, `next_action`, `terminal`, `semantic_summary`, `verify_state`, and `commit_state`

When no active transaction exists, the canonical materialized representation is:
- `active_tx: null`
- `status: null`
- `phase: null`
- `next_action: tx.begin`
- `terminal: false`
- `semantic_summary: null`
- `verify_state: null`
- `commit_state: null`

## 2. Event log
Retain canonical append-only history under `.agent/tx_event_log.jsonl`.

### Purpose
- rebuild source
- audit trail
- protocol history
- replay and integrity validation

### Role
The event log is authoritative for historical progression, but current resume should begin from materialized state whenever healthy.

A missing `.agent/tx_event_log.jsonl` indicates an uninitialized or damaged workspace, while a present-but-empty event log is a valid zero-event baseline.

## 3. Transaction ID issuance metadata
Introduce or stabilize `.agent/tx_id_counter.json`.

### Purpose
- issue monotonic transaction identifiers
- prevent ad hoc identity creation
- centralize new transaction allocation

### Required fields
- `last_issued_id`
- `updated_at`

### Initialization policy
- missing file may be treated as zero baseline for issuance metadata only
- malformed file must fail clearly and must not be silently treated as zero

### Representation policy
- `last_issued_id` remains an integer counter value
- issued `tx_id` values are represented as integers in JSON-facing artifacts

## 4. Session metadata
Session-related metadata may be retained or improved where useful, but it should not be required to understand which transaction to resume.

Any session design in `0.6.0` must remain secondary to the simpler transaction-centered protocol.

## Canonical Ordering and Durability

## Write-order rule
Canonical persistence should continue to follow strict ordering:

1. append event
2. update materialized transaction state
3. persist any required cursor / snapshot metadata

This preserves the project’s durability and replay guarantees.

## Durability goal
After any meaningful work-loop checkpoint, interruption should still leave enough canonical information to decide:

- what transaction is active
- what status it is in
- what happened most recently
- what action must happen next

## Resume Model

## Resume entrypoint
Resume should follow this logic:

1. initialize workspace
2. load canonical transaction state
3. validate materialized state
4. if state is missing or incomplete, rebuild from event log
5. inspect active transaction
6. if active transaction is terminal, no resumable work exists
7. if active transaction is non-terminal, resume that exact transaction
8. continue using canonical `next_action`

## Resume source-of-truth order
Resume decisions should prefer:

1. healthy materialized transaction state
2. canonical event-log rebuild when materialized state is missing, incomplete, or inconsistent
3. explicit failure when integrity is ambiguous and no safe deterministic continuation exists

## Resume invariants
Resume must:
- never mint a new `tx_id`
- reuse the exact existing active `tx_id`
- rely on top-level `next_action` as the primary continuation guide
- treat malformed canonical persistence as explicit failure rather than silent fallback
- never replace the active transaction with a heuristic candidate
- preserve exact active transaction identity
- preserve the distinction between non-terminal and terminal states
- preserve explicit end-of-transaction handling
- avoid duplicate logical completion when work was already committed or ended

## Post-terminal materialization
After terminal completion, a terminal transaction snapshot may remain materialized briefly.
A subsequent canonical materialized-state operation, `tx.clear_active`, clears the active slot after the terminal snapshot has been durably recorded.
`tx.clear_active` is not a canonical event-log event.

## Idempotent continuation requirements
Repeated resume of the same interrupted state should not corrupt the lifecycle.

The protocol should support safe repeated continuation for cases such as:
- already-verified transaction resumed before commit
- already-committed transaction resumed before terminal end
- terminal transaction encountered again after completion

## Identity Model

## `ticket_id`
- identifies the planned work item
- client-managed
- not the running transaction identity

## `tx_id`
- identifies one durable work-loop execution instance
- server-managed
- monotonic positive integer issuance semantics
- opaque and exact once issued
- stored in JSON-facing artifacts in a documented stable representation

### Recommended representation
Use monotonic positive integers for issuance semantics and represent them as integers in JSON-facing artifacts.

Examples:
- `1`
- `2`
- `3`

## `seq`
- identifies canonical append order of transaction events
- remains globally monotonic
- remains the canonical event ordering key

## `session_id`
- optional or secondary runtime context
- useful for observability
- not the primary basis for resumable correctness in `0.6.0`

## Sentinel elimination
Normal canonical behavior must not represent active transaction identity with sentinel values such as:
- `none`

Absence of an active transaction should be represented structurally, not by fake transaction identifiers.

## Timestamp Policy

## Allowed use
Timestamps may be used for:
- auditability
- observability
- debugging
- operator inspection
- anomaly diagnosis

## Disallowed use
Timestamps must not be used as:
- the primary canonical ordering key
- the primary active transaction selector
- the primary deterministic recovery mechanism

Canonical ordering and continuation should prefer:
- exact transaction identity
- exact current status
- exact next action
- event sequence order

## Compatibility Policy

## Historical logs
Historical logs may contain:
- legacy transaction ID formats
- older assumptions about active transaction representation
- older lifecycle behavior
- session-oriented or heuristic recovery assumptions

These histories should remain replayable.

## Compatibility rule
Historical data remains readable as historical state.

However, all new writes after `0.6.0` should follow the redesigned transaction protocol.

## No forced historical rewrite
Forward migration should not require rewriting all prior event history in place.

## New-write policy
After `0.6.0`:
- no new code path may derive `tx_id` from `ticket_id`
- no new normal-flow logic may use sentinel transaction IDs
- no new resume logic may depend on string-prefix or substring transaction heuristics
- no new logic may treat repository commit as terminal transaction success
- no new resume logic may treat planning artifacts as canonical runtime truth

## Scope

## In scope
- redefine transaction semantics around ticket completion
- define the transaction-centered resumable protocol
- define the canonical status model and allowed transitions
- define the role of `next_action` as the continuation contract
- keep canonical persistence minimal and transaction-centered
- formalize deterministic resume behavior
- introduce or stabilize monotonic `tx_id` issuance
- remove sentinel active-transaction semantics from normal flow
- preserve strict ordering for verify, commit, and terminal completion
- preserve compatibility for historical logs
- update tests and docs around interruption and continuation behavior

## Out of scope
- redesigning client planning formats
- replacing the append-only event log model
- broad unrelated refactors
- introducing distributed multi-writer transaction allocation
- requiring a database-backed implementation
- making session-parent modeling the primary correctness mechanism

## Implementation Strategy

### Phase 1: Define the resumable transaction protocol, state machine, and persistence contract
**Goals**
- Define the canonical meaning of a transaction.
- Define the transaction-centered protocol for ticket completion.
- Define the canonical state machine and continuation contract.
- Define the minimal persistence, rebuild, and issuance contract required for deterministic continuation.

**Tasks**
- define transaction semantics as a durable execution attempt
- define the roles of `ticket_id`, `tx_id`, `seq`, and bounded `session_id`
- define single-active-transaction rules
- define explicit terminal completion semantics
- define commit as non-terminal
- define the no-sentinel active-transaction policy
- define canonical statuses and their meanings
- define checkpoint events needed for continuation, including `tx.step.enter` as the canonical progress-checkpoint event
- define `next_action` semantics as the primary continuation guide
- define the canonical role of `.agent/tx_state.json`
- define the canonical role of `.agent/tx_event_log.jsonl`
- define the canonical role of `.agent/tx_id_counter.json`
- define write-order guarantees
- define rebuild responsibilities and fallback behavior
- define malformed versus missing artifact behavior

**Deliverables**
- authoritative transaction protocol contract
- authoritative identity-role contract
- canonical invariants for active transaction handling
- state-machine contract
- checkpoint event contract
- continuation / resume contract
- persistence contract
- rebuild contract
- issuance metadata contract

**Acceptance for phase**
- the plan clearly defines what a transaction is in this project
- the plan clearly distinguishes ticket identity from transaction identity
- the plan clearly states that commit is non-terminal and end is explicit
- the plan clearly constrains active transaction behavior
- every non-terminal state has a clear continuation meaning
- resume can be described primarily in terms of canonical transaction state plus top-level `next_action`
- there is a clear canonical resume entrypoint
- there is a clear authoritative append-only history source
- there is a clear deterministic transaction issuance model
- malformed persistence artifacts fail clearly rather than degrade silently

---

### Phase 2: Implement runtime identity and recovery simplifications
**Goals**
- Replace ticket-derived transaction identity with issued transaction IDs.
- Remove sentinel active-transaction semantics from normal flow.
- Simplify resume behavior so it continues the exact active transaction.
- Bound the role of session context without weakening exact active-transaction continuation.

**Tasks**
- replace ticket-derived transaction identity in new writes
- implement issued monotonic `tx_id` allocation during canonical begin only
- remove sentinel active transaction semantics from normal flow
- adopt structural no-active representation based on `active_tx: null`
- simplify exact active transaction continuation rules
- make materialized transaction state the primary resume anchor
- use event-history rebuild only when materialized state is missing, incomplete, or inconsistent
- bound the role of session context in correctness-sensitive logic
- define and implement historical compatibility behavior for legacy transaction IDs, sentinel-bearing histories, and older session-oriented assumptions

**Deliverables**
- simplified identity policy
- issued transaction ID behavior in runtime code
- sentinel-free active-transaction handling in runtime code
- simplified exact-active-transaction resume behavior
- compatibility guidance and bounded compatibility behavior for historical data

**Acceptance for phase**
- new runtime behavior does not derive transaction identity from ticket identity
- newly issued `tx_id` values are allocated only through canonical begin
- active transaction selection is exact and deterministic
- no-active state is represented structurally rather than by sentinel transaction identifiers
- resume behavior treats healthy materialized state as the primary resume entrypoint
- session context is bounded and no longer central to resumable correctness
- historical compatibility remains bounded and does not weaken strict new runtime semantics

---

### Phase 3: Harden with interruption-focused regression coverage and guidance
**Goals**
- Prove that the redesigned protocol survives interruption and resumes correctly.
- Add regression coverage for exact-active-transaction continuation and bounded compatibility behavior.
- Update documentation and operator guidance for the redesigned protocol.

**Tasks**
- add tests for interrupted in-progress transactions
- add tests for interrupted verify flows
- add tests for interrupted commit flows
- add tests for interrupted post-commit pre-terminal flows
- add tests for terminal re-entry and idempotent resume behavior
- add tests for malformed versus missing issuance metadata
- add tests for structural no-active representation and `tx.clear_active` behavior
- add tests for compatibility with historical legacy logs
- add tests for bounded compatibility behavior around legacy sentinel-bearing and older session-oriented histories
- update operator and developer guidance for the redesigned transaction protocol

**Deliverables**
- interruption-focused regression suite
- compatibility coverage
- documented operator and developer guidance

**Acceptance for phase**
- interruption cases resume deterministically
- duplicate continuation does not corrupt transaction state
- terminal transactions are not resumed as active work
- historical logs remain replayable under the documented policy
- no-active materialized-state behavior remains structurally explicit and stable under repeated resume

## Success Criteria
`0.6.0` is successful when the system can be described simply as follows:

- a ticket starts a durable transaction
- that transaction becomes the single active unit of work
- progress is durably checkpointed
- interruption does not lose the ability to continue
- resume always continues the same active transaction
- `next_action` tells the agent what to do next
- verify and commit are resumable checkpoints
- commit does not equal success
- explicit terminal end closes the transaction
- the system no longer relies on fragile identity heuristics to finish interrupted work

## Recommended Ticket Breakdown
The following ticket structure is recommended for `0.6.0` planning and execution.

### Phase 1
- `p1-t01` Define the canonical resumable work transaction model
- `p1-t02` Define the canonical state machine and continuation rules
- `p1-t03` Define persistence, rebuild, and issuance responsibilities

### Phase 2
- `p2-t01` Replace ticket-derived `tx_id` generation with issued transaction IDs
- `p2-t02` Remove sentinel active-transaction semantics from normal flow
- `p2-t03` Simplify resume logic to continue the exact active transaction
- `p2-t04` Bound session context and define historical compatibility behavior

### Phase 3
- `p3-t01` Add interruption and resume regression coverage for transaction checkpoints
- `p3-t02` Add idempotent continuation coverage for verify, commit, and terminal flows
- `p3-t03` Update documentation and operator guidance for the redesigned protocol