# Implementation Plan: 0.6.0 Redesign the work loop as a resumable transactional protocol (!!DO NOT UPDATE!!)

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
- Preserve bounded compatibility for historical materialized snapshots and legacy historical formats without allowing them to redefine the new canonical protocol.
- Minimize the canonical continuation surface to only the fields required for deterministic resume, explicit lifecycle control, replay integrity, and transaction ID issuance.

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

The redesign should prefer removing unnecessary continuation concepts over redefining them.

If a field is not required for exact active-transaction selection, deterministic continuation, replay integrity, or explicit terminal completion, it should not be part of the canonical protocol surface.

## Core Design Goal
Version `0.6.0` should redefine the work loop so that it behaves like a **true resumable transaction protocol for ticket completion**.

After `0.6.0`, the canonical model should make the following true:

1. A transaction is one durable execution attempt for one ticket.
2. A workspace may have at most one non-terminal active transaction at a time.
3. Resume always targets the exact active transaction, not a heuristically reconstructed replacement.
4. Current resumable state is explicit, materialized, and intentionally minimal.
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
- the current lifecycle state
- the current resumable checkpoint
- the current next required action
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
`session_id` may remain available as secondary runtime context, but it is not part of the canonical identity or continuation contract for `0.6.0`.

### Role
- observability
- correlation
- handoff continuity
- helper-call continuity when needed

### Non-role
`session_id` must not determine:
- active transaction identity
- active transaction selection
- deterministic resume correctness

## Server-owned transaction variables vs client-managed inputs

The runtime implementation under `src/` needs a stricter boundary between:
- **server-owned canonical protocol state**
- **server-owned replay / integrity support**
- **client-managed inputs and labels**

This distinction is necessary because `0.6.0` defines a resumable transaction protocol, not a client-managed ticket database.

### 1. Canonical continuation fields
These values define the minimal canonical continuation contract.
They are the fields required to resume the exact active transaction deterministically.

- `active_tx`
  - the currently active non-terminal transaction snapshot, or `null`
  - when non-null, it includes the exact active transaction identity, including `tx_id`
  - it is an identity-bearing active-transaction snapshot, not the canonical lifecycle-classification field
- `status`
  - the canonical lifecycle classification
  - it is represented only at the top level of the materialized continuation contract
  - one of the canonical status values when an active transaction exists, and `null` only in the no-active baseline representation
- `next_action`
  - the canonical machine-readable continuation directive
- `verify_state`
  - canonical verification checkpoint state
- `commit_state`
  - canonical commit checkpoint state
- `semantic_summary`
  - required concise summary of the current non-terminal work state
- `last_applied_seq`
  - the last event sequence durably materialized into current state

The canonical continuation contract is intentionally minimal.
Fields not required for exact active-transaction selection, deterministic continuation, replay integrity, or explicit terminal completion must not be treated as part of this contract.

### 2. Canonical replay, issuance, and integrity fields
These values support replay, issuance correctness, and integrity validation.

- `tx_id`
  - canonical runtime transaction identity
  - server-issued
  - integer-valued
  - not derived from `ticket_id`, `task_id`, or any other client label
- `seq`
  - canonical append order for transaction events
- `event_id`
  - event record identifier when present
- `last_issued_id`
  - issuance counter state for new canonical transaction IDs
- `rebuilt_from_seq`
  - rebuild checkpoint origin for current materialized state
- `integrity`
- `state_hash`
- `drift_detected`

These fields support correctness of replay, issuance, and validation, but they do not replace the canonical continuation role of `active_tx`, `status`, and `next_action`.

### 3. Derived diagnostics and workflow guidance
The server may return additional diagnostics and workflow guidance fields such as:
- `requires_followup`
- `followup_tool`
- `recommended_next_tool`
- `recommended_action`
- `recoverable`
- `blocked`
- `session_context`
- `active_tx_context`

These fields are derived outputs.
They may help operators or clients, but they must not redefine canonical transaction identity, canonical lifecycle state, or deterministic continuation.

### 4. Client-managed inputs
These values may be supplied by the client and may be persisted as metadata, but they are not the canonical runtime transaction identity.

#### Planning and human-facing identifiers
- `ticket_id`
  - planning/work-item identifier
  - client-managed
  - may be stored as transaction metadata
  - not the canonical runtime execution identifier
- `task_id`
  - helper-API compatibility label
  - client-managed
  - not part of the canonical `0.6.0` transaction identity model
  - must not be used to infer, reconstruct, or replace `tx_id`
- `title`
  - human-facing task title

#### Client-provided runtime context
- `session_id`
  - may be provided by the client
  - may be recovered when useful for observability, correlation, handoff continuity, or helper-call continuity
  - must not determine active transaction identity, active transaction selection, or deterministic resume correctness
- `agent_id`
- `user_intent`

#### Client-provided helper inputs
The server may accept helper-style request inputs such as:
- `status`
- `note`
- `summary`
- `path`
- `operation`
- `purpose`
- helper controls such as `timeout_sec`, `max_chars`, `max_events`, `include_diff`, `log`, `diff`, `failures`, and similar request parameters

Such inputs do not by themselves redefine canonical transaction identity or canonical lifecycle validity.

### 5. Design consequence for `ops_tools`
The intended `0.6.0` direction is:

1. transaction correctness is anchored on server-owned canonical transaction state
2. new transaction creation may accept client-managed planning inputs such as `ticket_id` and `title`
3. once a transaction exists, continuation should be anchored on the exact canonical transaction identity and canonical materialized state
4. helper-style client labels must not be allowed to redefine, infer, or reverse-map canonical transaction identity

### 6. Practical rule for future implementation work
When reviewing or changing runtime code, use this boundary:

- If a value determines canonical transaction identity, lifecycle ordering, replay integrity, materialized resumability, or issuance state, it is **server-owned**.
- If a value is provided for planning, naming, operator intent, or client-side workflow convenience, it is **client-managed**.
- Client-managed identifiers must not be promoted into canonical runtime identity by string-shape heuristics, reverse mapping, or replacement-ID synthesis.

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

`done` is the only successful terminal outcome in the canonical transaction model.

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
- the minimal canonical continuation contract in materialized state:
  - `active_tx`
  - `status`
  - `next_action`
  - `verify_state`
  - `commit_state`
  - `semantic_summary`
  - `last_applied_seq`
- canonical event history when rebuild is needed
- exact active transaction identity

Resume should not depend on:
- string-shape assumptions
- sentinel transaction identifiers
- timestamp-first selection
- planning-document status as a source of truth
- optional phase-style or step-style metadata

## 6. Planning artifacts are derived
Files under `docs/` are useful planning artifacts, but they are not canonical runtime state.

When maintained, they should align with runtime progress, but resume and lifecycle decisions must use the minimal canonical continuation contract and canonical event history.

## Canonical State Machine

Status classifies lifecycle state.
Canonical continuation dispatch is determined by `next_action`.

No implementation should override a valid canonical `next_action` with status-derived heuristics.
Status-specific “typical next action” text in this section is explanatory guidance only.

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
- otherwise proceed directly to explicit terminal completion

A verified transaction does not require a commit checkpoint when there are no repository changes to commit.
In that case, `verified -> done` is canonical and `committed` is not required as an intermediate status.

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
The event model should be organized around the minimal resumable checkpoints required for deterministic continuation.

Canonical core checkpoint events:
- `tx.begin`
- `tx.verify.start`
- `tx.verify.pass`
- `tx.verify.fail`
- `tx.commit.start`
- `tx.commit.done`
- `tx.commit.fail`
- `tx.end.done`
- `tx.end.blocked`

Commit checkpoint events are required only when an actual repository commit is attempted.

If verification succeeds and there are no repository changes:
- the transaction may proceed directly from `verified` to explicit terminal completion
- omitting `tx.commit.start` / `tx.commit.done` is canonical behavior

Additional progress events may exist for observability or tooling, but they are not required to define canonical resumable continuation.

## Persistence Model

## 1. Materialized state
Retain canonical materialized state under `.agent/tx_state.json`.

### Purpose
This is the canonical resume entrypoint.

It should capture at least:
- `active_tx`, which is `null` when no active transaction exists
- top-level current `status`
- top-level `next_action`
- top-level `semantic_summary`
- top-level `verify_state`
- top-level `commit_state`
- `last_applied_seq`
- current integrity fields needed for safe continuation and validation

### Role
- first source for resume
- machine-readable continuation state
- current canonical view of active transaction state, or the canonical no-active baseline representation

The materialized continuation contract is intentionally minimal.
Optional observability metadata may exist, but deterministic continuation must not depend on phase-style or step-style fields.

When no active transaction exists, the canonical materialized representation is:
- `active_tx: null`
- `status: null`
- `next_action: tx.begin`
- `semantic_summary: null`
- `verify_state: null`
- `commit_state: null`
- `last_applied_seq`, retaining the last materialized event sequence when available

In this no-active baseline, `status: null` is canonical and does not extend the active-transaction status set.
In this no-active baseline, `verify_state` and `commit_state` are `null`.

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
Session-related metadata may be retained where useful for observability, correlation, handoff continuity, or helper-call continuity.

It is not required to determine the active transaction or deterministic continuation.

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
5. if `active_tx` is `null`, no active transaction exists
6. otherwise resume that exact active transaction
7. continue using canonical `next_action`

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

When valid canonical `next_action` is present, implementations must prefer it over status-derived heuristics, phase-style metadata, step-style metadata, or reconstructed continuation guesses.

## Post-terminal materialization
After terminal completion, the transaction is no longer active.

Materialized state must not continue to expose that completed work as resumable active work.
Once materialized state reaches the canonical no-active baseline, `verify_state` and `commit_state` are `null`.
Terminal durability is preserved by canonical event history and any documented terminal snapshot handling, but terminal completion must not leave ambiguity about active resumability.

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

Compatibility handling is intentionally bounded.

It may normalize documented historical formats that remain deterministically replayable.
It must not silently reinterpret malformed, ambiguous, or non-deterministically replayable persistence as healthy canonical state.

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
- reduce the canonical continuation contract to the minimum fields required for deterministic resume
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
- define the minimal checkpoint events required for deterministic continuation
- define `next_action` semantics as the primary continuation guide
- define the canonical role of `.agent/tx_state.json`
- define the canonical role of `.agent/tx_event_log.jsonl`
- define the canonical role of `.agent/tx_id_counter.json`
- define write-order guarantees
- define rebuild responsibilities and fallback behavior
- define malformed versus missing artifact behavior
- remove or demote non-essential continuation concepts from the canonical protocol surface

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
- resume can be described primarily in terms of the minimal canonical continuation contract plus top-level `next_action`
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
- remove canonical dependence on non-essential fields such as phase-style or step-style progress metadata
- restrict active-slot semantics to non-terminal active transactions only
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
- add tests for structural no-active representation and terminal materialization behavior
- add tests for compatibility with historical legacy logs
- add tests for bounded compatibility behavior around legacy sentinel-bearing and older session-oriented histories
- add tests proving deterministic continuation does not depend on optional observability metadata
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
- the system resumes correctly without requiring auxiliary phase or step metadata

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
