# p1-t03 Specification: Persistence, Rebuild, and Issuance Responsibilities

## Status
- **Ticket**: `p1-t03`
- **Title**: Define persistence, rebuild, and issuance responsibilities
- **Canonical source**: `docs/v0.6.0/plan.md`
- **Source plan phase**: `Implementation Strategy / Phase 1`
- **Derived artifact type**: implementation-facing specification
- **Authority rule**: this document is derived from `plan.md` and must not add canonical requirements beyond it

## Purpose
This artifact translates the plan-defined materialized-state contract, event-log role, transaction-ID issuance metadata, write-order guarantees, rebuild fallback order, and malformed-versus-missing behavior into implementation-facing specification language for `p1-t03`.

It exists to support later implementation and verification work by:
- restating the plan-defined persistence model in implementation-oriented form
- making the source-of-truth order explicit for healthy resume and rebuild
- defining the narrow role of issuance metadata without promoting it into lifecycle state
- separating canonical requirements from current-code observations and downstream work planning

This document is not a replacement for `docs/v0.6.0/plan.md`. When wording here appears narrower or broader than the plan, the plan remains authoritative.

---

## Scope of this ticket
This ticket covers only the requirements allocated to `p1-t03`:

- `REQ-P1-PERSISTENCE`

Within that scope, this ticket may restate persistence-relevant implications of identity and checkpoint semantics already defined by `plan.md`, but it does not redefine or newly allocate `REQ-P1-IDENTITY` or `REQ-P1-CHECKPOINTS`.

This ticket does **not** define:
- the transaction meaning and identity semantics already allocated to `p1-t01` except where needed for persistence interpretation
- the broader canonical state-machine contract already allocated to `p1-t02` except where needed for persistence interpretation
- runtime code changes
- additional canonical persistence artifacts beyond those named in `plan.md`

---

## Canonical source sections used
The following `plan.md` sections are the canonical sources for this artifact:

- `Persistence Model`
- `Canonical Ordering and Durability`
- `Resume Model`
- `Identity Model`
- `Compatibility Policy`
- `Implementation Strategy`

Supporting evidence inputs used for implementation targeting, but not as canonical requirement sources:

- `docs/v0.6.0/phase0-implementation-map.md`

---

## 1. Canonical persistence artifact model

## 1.1 Canonical artifact set
For `0.6.0`, the canonical persistence surface remains intentionally small.

The canonical runtime persistence artifacts are:

- `.agent/tx_state.json`
- `.agent/tx_event_log.jsonl`
- `.agent/tx_id_counter.json`

These artifacts together support:
- deterministic continuation
- replay and rebuild
- integrity validation
- exact transaction ID issuance

No additional artifact should be treated as canonical runtime truth unless `plan.md` explicitly defines it.

## 1.2 Non-canonical artifacts
Planning and operator-support artifacts may still exist, but they are not canonical runtime persistence.

Examples of non-canonical or derived artifacts include:
- files under `docs/`
- other convenience or client-managed metadata

Review implication:
- later implementation must not let planning artifacts or other derived artifacts redefine active transaction selection, resume truth, or issuance state

---

## 2. Materialized state contract: `.agent/tx_state.json`

## 2.1 Purpose
`tx_state.json` is the canonical resume entrypoint.

Its role is to provide:
- the current canonical active transaction view, or
- the canonical no-active baseline representation

Healthy resume should begin from this materialized state before falling back to rebuild.

## 2.2 Minimum continuation contract
The plan requires materialized state to capture at least:

- `active_tx`
- top-level `status`
- top-level `next_action`
- top-level `semantic_summary`
- top-level `verify_state`
- top-level `commit_state`
- `last_applied_seq`
- current integrity fields needed for safe continuation and validation

This is the minimal canonical continuation surface.

Review implication:
- deterministic continuation must not depend on optional phase-style, step-style, or convenience metadata when the required top-level continuation contract is available

## 2.3 Required no-active baseline
When no active transaction exists, the canonical materialized representation is:

- `active_tx: null`
- `status: null`
- `next_action: tx.begin`
- `semantic_summary: null`
- `verify_state: null`
- `commit_state: null`
- `last_applied_seq`, retaining the last materialized event sequence when available

Important consequences:
- `status: null` in this case is canonical
- `status: null` here does **not** add a new active-transaction lifecycle status
- no completed transaction should remain exposed as resumable active work once the system is in this baseline

## 2.4 Role boundary
`tx_state.json` is:
- the first source for resume
- the machine-readable continuation snapshot
- the current canonical active-transaction view when healthy

`tx_state.json` is not:
- a replacement for append-only history
- permission to ignore event-log integrity
- permission to recover from malformed canonical state by silent heuristic invention

## 2.5 Healthy materialized-state expectation
A healthy materialized state should be sufficient to answer:

- whether an active transaction exists
- what the canonical status is
- what the canonical next action is
- what the latest verification or commit checkpoint state is
- what event sequence was last materialized

---

## 3. Event log contract: `.agent/tx_event_log.jsonl`

## 3.1 Purpose
`tx_event_log.jsonl` is the canonical append-only transaction history.

Its role is:
- rebuild source
- audit trail
- protocol history
- replay and integrity validation source

## 3.2 Relationship to materialized state
The event log is authoritative for historical progression.

However, healthy current resume should start from materialized state whenever materialized state is valid.

This means:
- current continuation entrypoint: `tx_state.json`
- historical authority and rebuild source: `tx_event_log.jsonl`

Neither should displace the other from its canonical role.

## 3.3 Missing versus empty behavior
The plan distinguishes sharply between these cases:

### Missing event log
A missing `.agent/tx_event_log.jsonl` indicates:
- an uninitialized workspace, or
- a damaged workspace

It is **not** the same as a healthy zero-event baseline.

### Present-but-empty event log
A present-but-empty `.agent/tx_event_log.jsonl` is:
- a valid zero-event baseline

This is the canonical initialized empty-history case.

## 3.4 Malformed event-log behavior
Malformed canonical persistence must fail explicitly.

Therefore:
- malformed event-log content must not be silently treated as an empty baseline
- malformed event-log content must not be silently treated as healthy resumable history
- malformed event-log handling must preserve explicit failure semantics

Review implication:
- later implementation may support bounded repair or explicit diagnostics, but must not degrade malformed canonical history into healthy baseline behavior without explicit repair semantics

---

## 4. Transaction ID issuance metadata: `.agent/tx_id_counter.json`

## 4.1 Purpose
`tx_id_counter.json` exists to:
- issue monotonic transaction identifiers
- prevent ad hoc identity creation
- centralize new transaction allocation

This artifact is part of canonical persistence because issuance correctness is part of the protocol surface.

## 4.2 Required fields
The plan requires:

- `last_issued_id`
- `updated_at`

These fields define issuance metadata only.
They do not define lifecycle state.

## 4.3 Initialization policy
The plan defines asymmetric handling for missing versus malformed issuance metadata.

### Missing issuance file
A missing issuance file may be treated as:
- zero baseline for issuance metadata only

### Malformed issuance file
A malformed issuance file must:
- fail clearly
- not be silently treated as zero

This distinction is part of the canonical persistence contract.

## 4.4 Representation policy
The plan requires:
- `last_issued_id` remains an integer counter value
- issued `tx_id` values are represented as integers in JSON-facing artifacts

Review implication:
- later implementation must not switch canonical issuance to client-shaped string synthesis, ticket-derived IDs, or helper-label-derived IDs

## 4.5 Role boundary
`tx_id_counter.json` is:
- issuance metadata

It is not:
- lifecycle state
- active-transaction selector
- a substitute for `tx_state.json`
- a substitute for event history

---

## 5. Canonical write ordering and durability

## 5.1 Required ordering
The plan requires strict canonical write ordering:

1. append event
2. update materialized transaction state
3. persist any required cursor / snapshot metadata

This ordering is canonical.

## 5.2 Why ordering matters
The purpose of the ordering rule is to preserve:
- durability guarantees
- replay correctness
- rebuild safety
- deterministic continuation after interruption

## 5.3 Checkpoint durability goal
After any meaningful work-loop checkpoint, interruption should still leave enough canonical information to decide:

- what transaction is active
- what status it is in
- what happened most recently
- what action must happen next

Review implication:
- later implementation must evaluate persistence changes primarily against post-interruption resumability, not just nominal success-path convenience

## 5.4 Commit and terminal separation in persistence
Persistence ordering must preserve the distinction between:
- verification checkpoints
- commit checkpoints
- terminal completion checkpoints

A successful commit must remain non-terminal until explicit end-of-transaction handling is persisted.

This ticket does not redefine the state machine, but it does require persistence behavior to preserve that distinction.

---

## 6. Rebuild and resume source-of-truth order

## 6.1 Resume entrypoint order
The canonical resume flow is:

1. initialize workspace
2. load canonical transaction state
3. validate materialized state
4. if state is missing or incomplete, rebuild from event log
5. if `active_tx` is `null`, no active transaction exists
6. otherwise resume that exact active transaction
7. continue using canonical `next_action`

This order is canonical and should be preserved in implementation.

## 6.2 Source-of-truth preference order
Resume decisions should prefer:

1. healthy materialized transaction state
2. canonical event-log rebuild when materialized state is missing, incomplete, or inconsistent
3. explicit failure when integrity is ambiguous and no safe deterministic continuation exists

Important consequence:
- rebuild is fallback for unhealthy or unavailable materialized state
- rebuild is not a license to heuristically replace healthy materialized continuation

## 6.3 Exact identity preservation during rebuild
When rebuild is needed, it must preserve:
- exact active transaction identity
- exact non-terminal versus terminal distinction
- explicit end-of-transaction handling
- exact continuation via canonical `next_action`

Rebuild must not:
- mint a new `tx_id`
- replace the active transaction with a heuristic candidate
- use planning-document status as runtime truth
- use client-managed identifiers as replacement canonical identity

## 6.4 Post-terminal materialization rule
After terminal completion:
- the transaction is no longer active
- materialized state must not continue to expose completed work as resumable active work

Once materialized state reaches the no-active baseline:
- `verify_state` is `null`
- `commit_state` is `null`

Historical durability remains preserved by canonical event history and any documented terminal snapshot handling, but active resumability must not remain ambiguous.

---

## 7. Missing, incomplete, inconsistent, and malformed behavior

## 7.1 Missing materialized state
The plan states that resume should rebuild from the event log if materialized state is missing or incomplete.

This is different from malformed canonical persistence, which must not be silently treated as healthy continuation state.

## 7.2 Incomplete materialized state
The plan states that resume should rebuild from the event log if materialized state is incomplete.

Review implication:
- later implementation should preserve the plan’s distinction between healthy materialized state, rebuild-triggering materialized-state problems, and malformed canonical persistence

## 7.3 Malformed canonical persistence
Malformed canonical persistence must be treated as explicit failure rather than silent fallback.

This applies to malformed canonical artifacts such as:
- malformed event history
- malformed issuance metadata

This ticket does not mandate a specific user-facing error string, but it does require explicit failure semantics.

## 7.4 Bounded compatibility does not weaken failure semantics
The plan allows bounded compatibility for historical logs and historical materialized snapshots.

However, that compatibility does **not** permit:
- malformed canonical persistence to silently become healthy baseline
- historical ambiguity to redefine the `0.6.0` canonical protocol

---

## 8. Compatibility interpretation for persistence work

## 8.1 Historical logs
Historical logs may remain readable under bounded compatibility behavior.

But historical compatibility must not:
- redefine canonical identity
- redefine canonical continuation rules
- weaken malformed-history failure semantics

## 8.2 Historical snapshots
Historical materialized snapshots may also receive bounded compatibility handling.

But such handling must remain subordinate to:
- the `0.6.0` minimal continuation contract
- explicit integrity validation
- exact active-transaction identity preservation

## 8.3 Planning and client artifacts
Derived planning artifacts may align with runtime progress, but they are not canonical runtime state.

Therefore:
- they may assist operator workflow
- they must not drive resume truth
- they must not override canonical persistence

---

## 9. Implementation-facing review targets

## 9.1 Artifact-role review targets
Later implementation work should verify that:

- `tx_state.json` is treated as the first healthy resume entrypoint
- `tx_event_log.jsonl` is treated as authoritative append-only history and rebuild source
- `tx_id_counter.json` is treated as issuance metadata only
- no other artifact is promoted into canonical runtime state without plan support

## 9.2 Missing-versus-malformed review targets
Later implementation work should verify that:

- missing event log is treated as uninitialized or damaged, not as healthy empty baseline
- present-but-empty event log is treated as valid zero-event baseline
- missing issuance metadata may be treated as zero issuance baseline only
- malformed issuance metadata fails clearly
- malformed canonical persistence does not degrade silently into healthy baseline behavior

## 9.3 Ordering and durability review targets
Later implementation work should verify that:

- event append happens before materialized state update
- materialized state update happens before any required cursor or snapshot metadata persistence
- interruption after a meaningful checkpoint still leaves enough canonical information for deterministic continuation or explicit failure

## 9.4 Rebuild-order review targets
Later implementation work should verify that:

- healthy materialized state is preferred over rebuild
- rebuild occurs when materialized state is missing or incomplete, and remains the canonical fallback when materialized continuation cannot be safely used
- rebuild preserves exact active transaction identity
- rebuild does not mint replacement IDs
- rebuild does not select active work via planning status or heuristic ticket substitution

## 9.5 Active-versus-terminal review targets
Later implementation work should verify that:

- no-active baseline is structurally explicit
- terminally completed work does not remain materialized as active resumable work
- `verify_state` and `commit_state` are cleared in the no-active baseline
- terminal history remains preserved in canonical event history

---

## 10. Traceability matrix

| Requirement / persistence concern | Canonical source sections | Required interpretation in this artifact | Primary runtime review targets |
| --- | --- | --- | --- |
| Materialized state is the canonical resume entrypoint | `Persistence Model`, `Resume Model` | Healthy resume starts from `tx_state.json` before rebuild fallback | materialized-state load and validation paths |
| Event log is authoritative history and rebuild source | `Persistence Model`, `Resume Model` | `tx_event_log.jsonl` preserves append-only protocol history and drives rebuild when needed | event append, replay, rebuild, integrity logic |
| No-active baseline is explicit | `Persistence Model`, `Resume Model` | `active_tx: null`, `status: null`, `next_action: tx.begin`, `semantic_summary: null`, `verify_state: null`, `commit_state: null` | post-terminal materialization and no-active resume behavior |
| Missing vs empty event log distinction | `Persistence Model` | missing log means uninitialized/damaged; present-but-empty log is valid zero-event baseline | startup, initialization, rebuild entry logic |
| Issuance metadata is canonical and limited in role | `Persistence Model`, `Identity Model` | `tx_id_counter.json` issues monotonic integer `tx_id` values and does not define lifecycle state | tx ID allocation and issuance validation paths |
| Missing vs malformed issuance metadata distinction | `Persistence Model`, `Compatibility Policy` | missing issuance file may be zero baseline only for issuance; malformed file fails clearly | issuance metadata read/validate paths |
| Strict write ordering is preserved | `Canonical Ordering and Durability` | append event -> update materialized state -> persist required cursor/snapshot metadata | event/state persistence orchestration |
| Rebuild preference and fallback order | `Resume Model` | prefer healthy materialized state; rebuild only when state is missing/incomplete/inconsistent; otherwise fail explicitly when integrity is ambiguous | rebuild dispatcher and resume selection logic |
| Malformed canonical persistence remains explicit failure | `Resume Model`, `Compatibility Policy` | malformed canonical artifacts must not silently degrade into healthy baseline behavior | persistence validation and repair/error handling |

---

## 11. Current-code observation boundaries

This section is intentionally non-canonical.

### 11.1 What this ticket should evaluate in runtime code later
Based on the phase 0 implementation map, later implementation work should review persistence and rebuild behavior primarily in:

- `src/agentops_mcp_server/state_store.py`
- `src/agentops_mcp_server/state_rebuilder.py`
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/repo_context.py`

### 11.2 Why this remains non-canonical
Those file references are implementation-targeting observations only.

They do not add new persistence requirements beyond `plan.md`.

---

## 12. Input sufficiency check

The ticket inputs are sufficient for this ticket scope.

### Checked inputs
- `docs/v0.6.0/plan.md`
- `docs/v0.6.0/phase0-implementation-map.md`

### Sufficiency result
These inputs are:
- complete enough to define the canonical persistence, rebuild, and issuance responsibilities allocated to `p1-t03`
- non-contradictory for the scope of this ticket
- sufficient without inventing additional persistence artifacts or lifecycle semantics

### Constraint reminder
Future implementation tickets must continue to derive runtime changes from `plan.md`, using this artifact as an implementation-facing restatement rather than a new source of canonical truth.

---

## 13. Acceptance-criteria check

### Criterion: Materialized-state requirements match the top-level minimal continuation contract in `plan.md`
Satisfied by:
- Sections `2.1` through `2.5`
- Section `6.1`

### Criterion: The event-log role is described as authoritative history and rebuild source without displacing materialized state as primary healthy resume entrypoint
Satisfied by:
- Sections `3.1` through `3.4`
- Sections `6.1` and `6.2`

### Criterion: The issuance metadata contract preserves integer `tx_id` issuance semantics and clear malformed-file failure behavior
Satisfied by:
- Sections `4.1` through `4.5`

### Criterion: The artifact does not invent additional canonical persistence behavior beyond `plan.md`
Satisfied by:
- authority rule in `Status`
- scope limitation in `Scope of this ticket`
- source restrictions in `Canonical source sections used`
- repeated boundary statements throughout sections `1`, `7`, and `8`

---

## 14. Non-goals reminder for downstream implementation
Later implementation work for persistence should **not**:

- treat planning artifacts as canonical runtime state
- silently downgrade malformed canonical persistence into healthy baseline behavior
- use issuance metadata as lifecycle truth
- replace healthy materialized-state resume with heuristic event-log-first selection
- mint replacement `tx_id` values during resume
- redefine bounded compatibility as permission to weaken `0.6.0` canonical semantics

---