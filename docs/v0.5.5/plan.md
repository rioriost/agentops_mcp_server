# Implementation Plan: 0.5.5 Redesign canonical identifiers around a robust session / transaction / event model

## Objectives
- Introduce a clearer server-managed identity model for sessions, transactions, and events.
- Replace ticket-derived transaction identifiers with monotonic issued transaction IDs.
- Introduce a monotonic issued session identifier model for deterministic resume and recovery.
- Preserve the existing monotonic event sequence model as the canonical event-ordering mechanism.
- Keep timestamps as observability metadata rather than canonical ordering keys.
- Remove normal-flow dependence on sentinel identifiers such as `none`.
- Reduce lifecycle ambiguity by separating:
  - `session_id`
  - `tx_id`
  - `event seq`
  - `ticket_id`
- Add canonical parent logs for sessions and transactions so recovery does not depend solely on replaying detailed event history.
- Preserve compatibility for historical logs while making all new writes follow the new identity model.
- Add regression coverage for issuance, recovery, lifecycle checks, and compatibility.

## Background
Version 0.5.4 focused on making lifecycle workflow guidance more machine-readable and safer for agent-driven operation.

That work improved how agents understand:
- canonical status,
- canonical phase,
- next action,
- follow-up requirements,
- and recovery guidance.

However, debugging since then has exposed a deeper structural problem: the system does not yet separate its canonical server-managed identities strongly enough.

Today, several concerns are entangled:
- `ticket_id` identifies the user-visible work item,
- `tx_id` identifies a concrete transaction instance,
- `session_id` identifies the runtime session context,
- `seq` identifies canonical event ordering,
- and timestamps provide observability.

Those responsibilities should be distinct, but in practice the current model still allows ambiguity:
- `tx_id` may be partially treated as ticket-derived,
- sentinel values such as `none` still appear in normal-flow logic,
- session recovery is more artifact-driven than identity-driven,
- and detailed event history is carrying too much parent-level state reconstruction burden.

A more robust model should follow a simple hierarchy:

1. one session contains many transactions
2. one transaction contains many events

This is the same shape used by relational systems:
- parent session record
- child transaction record
- child event record

That structure is better for:
- deterministic recovery,
- lifecycle validation,
- rebuild correctness,
- observability,
- and long-term maintainability.

## Problem Statement
The current canonical identity model is under-specified and overly entangled.

In particular:
- `ticket_id` and `tx_id` are not cleanly separated in all code paths,
- `session_id` is important but not modeled as a first-class monotonic server-managed identifier,
- `tx_event_log.jsonl` carries both detailed lifecycle history and too much effective parent-state reconstruction burden,
- some comparisons still depend on string shape or sentinel handling,
- and timestamps are at risk of being used as ordering hints when ordering should instead be identity- or sequence-driven.

This creates avoidable complexity in:
- begin-vs-resume logic,
- active transaction mismatch checks,
- session recovery,
- materialized-state vs rebuilt-state conflict handling,
- helper bootstrap behavior,
- and regression test design.

## Desired Outcome
After 0.5.5:
- sessions, transactions, and events are modeled as separate canonical layers,
- `session_id` is a server-managed monotonic identifier,
- `tx_id` is a server-managed monotonic identifier,
- `seq` remains the canonical event-ordering identifier,
- timestamps remain observational metadata only,
- `.agent/session_log.jsonl` exists as a canonical session-parent log,
- `.agent/tx_log.jsonl` exists as a canonical transaction-parent log,
- `.agent/tx_event_log.jsonl` remains the canonical detailed event log,
- new writes no longer use ticket-derived transaction identifiers,
- normal lifecycle behavior no longer uses sentinel transaction identifiers such as `none`,
- recovery prefers exact identifier matching over timestamp heuristics,
- and historical logs remain replayable under a documented compatibility policy.

## Design Principles

### 1. Distinct identifiers must have distinct responsibilities
The canonical server-managed identifiers should have the following roles:

- `session_id`
  - identifies one runtime session context
- `tx_id`
  - identifies one concrete transaction instance
- `seq`
  - identifies canonical event ordering
- `ticket_id`
  - identifies the user-visible or plan-visible work item

These must not be partially merged.

### 2. Parent-child structure should be explicit
Canonical storage should model:
- sessions as parents of transactions
- transactions as parents of events

This should be explicit in persisted artifacts, not only inferred through replay.

### 3. Ordering must not depend on timestamps
Timestamps are useful for:
- debugging,
- observability,
- auditability,
- and human interpretation.

Timestamps must not be the primary determinant of canonical ordering or deterministic recovery.

### 4. Issuance must be centralized
Only one canonical issuance path may mint:
- a new `session_id`
- or a new `tx_id`

### 5. Replay remains authoritative for event history
The event log remains the canonical detailed lifecycle history.
Parent logs improve robustness and lookup behavior, but do not replace detailed event history.

### 6. Simpler identifiers should reduce logic, not hide errors
The identity redesign should simplify:
- comparisons,
- recovery,
- validation,
- and testing

without weakening:
- lifecycle ordering,
- explicit terminal-state handling,
- or replay integrity.

## Canonical Identity Model

## 1. Session identifiers
Sessions should become first-class server-managed identifiers.

### Issuance rule
Session IDs are monotonic positive integers:
- initial value: `0`
- first issued session ID: `1`
- then `2`, `3`, `4`, ...

### Semantics
A `session_id` identifies one runtime session context.
A session may contain multiple transactions.
A session may remain open, become closed, or become abandoned depending on policy.

### Storage representation
Recommended:
- numeric issuance semantics
- string serialization in JSON-facing artifacts

Examples:
- `"1"`
- `"2"`
- `"3"`

## 2. Transaction identifiers
Transaction IDs should also be monotonic positive integers.

### Issuance rule
Transaction IDs are monotonic positive integers:
- initial value: `0`
- first issued transaction ID: `1`
- then `2`, `3`, `4`, ...

### Semantics
A `tx_id` identifies one concrete transaction instance only.
It is not derived from `ticket_id`.
A single `ticket_id` may correspond to multiple historical transactions over time.

### Storage representation
Recommended:
- numeric issuance semantics
- string serialization in JSON-facing artifacts

Examples:
- `"1"`
- `"2"`
- `"3"`

## 3. Event sequence
The existing event sequence model should remain the canonical ordering mechanism.

### Semantics
`seq` is:
- globally monotonic,
- append-only,
- and the canonical event-ordering identity.

This is already the correct role for event sequencing and should be preserved.

## 4. Timestamps
Timestamps remain useful, but their role must be clearly bounded.

### Allowed use
Timestamps may be used for:
- observability,
- debug output,
- operator inspection,
- anomaly diagnosis,
- and non-canonical reporting.

### Disallowed use
Timestamps must not become:
- the canonical ordering mechanism,
- the primary resume-selection mechanism,
- or the primary recovery disambiguation mechanism.

If deterministic recovery must choose between candidates, it should prefer:
- exact canonical identifiers,
- canonical status,
- canonical phase,
- and event sequence metadata

before using timestamps for human-oriented diagnostics.

## Canonical Persistence Layout

## A. Session parent log
Introduce:

- `.agent/session_log.jsonl`

This log represents session-parent records.

### Purpose
- support deterministic session lookup
- support session-aware recovery
- record session lifecycle metadata
- reduce the need to infer current session state only from detailed events

### Suggested record shape
Each record should include at least:
- `session_id`
- `created_at`
- `updated_at`
- `status`
- `first_tx_id`
- `last_tx_id`
- `last_event_seq`

### Notes
This is analogous to a `sessions` table in a relational system.

## B. Transaction parent log
Introduce:

- `.agent/tx_log.jsonl`

This log represents transaction-parent records.

### Purpose
- support deterministic active-transaction lookup
- separate transaction metadata from detailed event history
- make rebuild and resume more robust
- reduce parent-state inference burden on the event log alone

### Suggested record shape
Each record should include at least:
- `tx_id`
- `session_id`
- `ticket_id`
- `created_at`
- `updated_at`
- `status`
- `phase`
- `terminal`
- `first_event_seq`
- `last_event_seq`

### Notes
This is analogous to a `transactions` table in a relational system.

## C. Detailed event log
Retain:

- `.agent/tx_event_log.jsonl`

### Purpose
- canonical append-only detailed lifecycle history
- replay input
- diagnostics and auditing
- exact event-level forensic trace

### Suggested record shape
Each record should continue to include the detailed event information already needed, including:
- `seq`
- `tx_id`
- `session_id`
- `event_type`
- `phase`
- `step_id`
- `ts`
- `payload`

### Notes
This is analogous to an `events` table.

## D. Counter metadata
The system needs server-managed issuance metadata.

There are two viable approaches.

### Option 1: Separate counter files
- `.agent/session_id_counter.json`
- `.agent/tx_id_counter.json`

Suggested fields:
- `last_issued_id`
- `updated_at`

### Option 2: Unified counter state
- `.agent/id_counters.json`

Suggested fields:
- `last_session_id`
- `last_tx_id`
- `last_event_seq`
- `updated_at`

### Recommendation
Prefer a unified counter state if implementation complexity remains manageable, because it centralizes identity allocator state.

However, if the existing event sequence handling is already stable and separate, introducing:
- `.agent/session_id_counter.json`
- `.agent/tx_id_counter.json`

first is still a valid incremental path.

## Scope

### In scope
- define the canonical server-managed identity hierarchy:
  - session
  - transaction
  - event
- add `.agent/session_log.jsonl`
- add `.agent/tx_log.jsonl`
- preserve `.agent/tx_event_log.jsonl` as the detailed canonical event history
- add monotonic `session_id` issuance
- add monotonic `tx_id` issuance
- define issuance metadata storage
- replace ticket-derived transaction ID generation
- remove sentinel transaction IDs from normal canonical behavior
- update lifecycle comparison logic to prefer exact identity matching
- update recovery ordering to prefer identifiers over timestamps
- preserve the current `seq` model
- document whether `event_id` is retained or removed
- update tests and docs

### Out of scope
- redesigning `ticket_id`
- changing event taxonomy
- weakening replay strictness
- rewriting historical logs in place
- replacing the canonical event log model
- broad refactors unrelated to identity and lifecycle correctness
- introducing distributed multi-writer event allocation semantics

## Compatibility Policy

## Historical logs
Historical logs may already contain:
- legacy transaction IDs
- legacy session behavior
- legacy transaction-parent assumptions
- and no parent logs for sessions/transactions

0.5.5 should preserve replay compatibility for those histories.

### Recommended policy
- historical event logs remain replayable
- historical legacy `tx_id` values remain readable as opaque identifiers
- historical session context may remain partially inferred where parent logs do not exist
- all newly issued session and transaction identifiers use the new monotonic scheme
- the system does not require rewriting old histories to adopt the new write policy

## New writes
After 0.5.5:
- no new code path may derive `tx_id` from `ticket_id`
- no new code path may treat `none` as a normal canonical `tx_id`
- no new code path may treat timestamps as canonical ordering keys
- all new session creation must use an issued monotonic `session_id`
- all new transaction begin paths must use an issued monotonic `tx_id`
- all new detailed events continue to use monotonic `seq`

## Recovery Model

## Active session recovery
Deterministic recovery should prefer canonical identity and state over timestamps.

### Recommended lookup order
1. materialized active session state, when healthy
2. latest non-closed session from `session_log.jsonl`
3. session reconstructed from canonical transaction and event state
4. failure if state is ambiguous and no safe deterministic candidate exists

Timestamps may be used for diagnostics, not primary selection.

## Active transaction recovery
Deterministic transaction recovery should also prefer canonical identity and state.

### Recommended lookup order
1. materialized active transaction, when healthy
2. latest non-terminal transaction from `tx_log.jsonl`
3. replay/rebuild from `tx_event_log.jsonl`
4. failure if ambiguous and not safely resolvable

Timestamps again remain diagnostic only.

## Session context recovery for lifecycle tools
When lifecycle tools must recover session context, they should prefer:
1. explicit `session_id`
2. exact matching `tx_id`
3. exact matching `session_id` parent context
4. exact matching `ticket_id` only when transaction identity is unavailable
5. bounded fallback
6. explicit failure when recovery is ambiguous

This prevents timestamp drift from becoming a hidden ordering mechanism.

## Event identity policy

## `seq`
Retain `seq` as the only canonical event identity needed for ordering.

## `event_id`
The current system should evaluate whether `event_id` is still needed.

### Recommendation
Do not require `event_id` as part of the 0.5.5 redesign unless a concrete need exists.

Reasons:
- `seq` already provides canonical global event identity for ordering
- current architecture is local and append-oriented
- event identity beyond `seq` appears to provide limited additional value in this model

If `event_id` remains present for compatibility, it should be treated as optional metadata rather than a core canonical ordering key.

## Implementation Strategy

### Phase 1: Define the canonical identity hierarchy and persistence model
**Goals**
- Finalize the parent-child identity model.
- Define the canonical roles of:
  - `session_id`
  - `tx_id`
  - `seq`
  - `ticket_id`
  - timestamps

**Tasks**
- Define the canonical identity hierarchy:
  - session -> transaction -> event
- Define parent-log responsibilities for:
  - `session_log.jsonl`
  - `tx_log.jsonl`
- Define detailed-event responsibilities for:
  - `tx_event_log.jsonl`
- Define the exact role of timestamps and explicitly reject timestamp-driven canonical ordering.
- Decide whether counter metadata is separate or unified.
- Decide whether `event_id` remains optional compatibility metadata or is removed entirely from new logic.

**Deliverables**
- authoritative identity model
- persistence-layout contract
- server-managed identifier responsibilities
- bounded timestamp policy

**Acceptance for phase**
- there is one documented authoritative identity model
- each identifier has one clear canonical role
- the parent/child log structure is unambiguous
- timestamps are explicitly non-canonical for ordering

---

### Phase 2: Implement monotonic session and transaction issuance
**Goals**
- Introduce canonical issuance for sessions and transactions.
- Make issuance deterministic and centralized.

**Tasks**
- implement monotonic session issuance
- implement monotonic transaction issuance
- add issuance metadata storage
- define initialization behavior for missing issuance metadata
- define failure behavior for malformed issuance metadata
- ensure only canonical creation paths mint new IDs

**Deliverables**
- session issuance helper(s)
- transaction issuance helper(s)
- issuance metadata validation rules

**Acceptance for phase**
- a clean workspace can issue session `1`
- a clean workspace can issue transaction `1`
- repeated issuance increments deterministically
- malformed issuance metadata fails clearly

---

### Phase 3: Introduce parent logs for sessions and transactions
**Goals**
- Persist canonical parent-level session and transaction metadata.
- Reduce over-reliance on detailed event replay for parent lookups.

**Tasks**
- add `.agent/session_log.jsonl`
- add `.agent/tx_log.jsonl`
- define append/update policy for parent-log records
- define consistency relationship between:
  - parent logs
  - materialized state
  - detailed event log
- define how parent logs are updated during lifecycle transitions

**Deliverables**
- session parent log
- transaction parent log
- parent-log consistency rules

**Acceptance for phase**
- parent logs can identify active or most recent session/transaction state deterministically
- parent logs remain aligned with canonical lifecycle changes
- parent logs improve lookup without replacing detailed event history

---

### Phase 4: Simplify lifecycle validation around exact identity
**Goals**
- Remove string-shape heuristics and sentinel logic from normal flow.
- Make begin/resume validation exact and explicit.

**Tasks**
- remove ticket-derived `tx_id` assumptions
- remove `tx-` prefix or substring comparison logic where no longer needed
- eliminate normal-flow dependence on `tx_id="none"`
- update active transaction mismatch logic to use exact identity
- update begin-required checks to depend on missing canonical identifiers rather than sentinel text
- keep `ticket_id` checks explicit and separate from `tx_id` checks

**Deliverables**
- simpler lifecycle validation logic
- exact identifier-based mismatch behavior
- removal of sentinel-driven normal flow

**Acceptance for phase**
- begin-required behavior is identifier-based, not sentinel-based
- active mismatch behavior does not depend on string-shape heuristics
- transaction identity and ticket identity remain distinct in validation logic

---

### Phase 5: Update recovery and rebuild behavior
**Goals**
- Make recovery deterministic using canonical parent and child identity layers.
- Reduce ambiguity between materialized and rebuilt state.

**Tasks**
- update active session recovery to prefer canonical session identity
- update active transaction recovery to prefer canonical transaction identity
- update session-context recovery ordering for lifecycle tools
- update rebuild/materialized conflict handling to use exact identifiers
- ensure timestamps remain non-canonical in recovery decisions
- ensure helper/bootstrap paths do not synthesize replacement session or transaction IDs

**Deliverables**
- recovery logic aligned with exact identity matching
- rebuild logic aligned with parent-child identity model
- deterministic recovery policy

**Acceptance for phase**
- recovery prefers exact identifiers over timestamps
- rebuild logic does not depend on identifier string shape
- ambiguous cases fail explicitly instead of silently guessing

---

### Phase 6: Preserve compatibility and migrate tests
**Goals**
- Keep historical logs readable.
- Update the test suite to reflect the new canonical identity structure.

**Tasks**
- identify tests assuming:
  - transaction IDs embed ticket information
  - `tx_id` starts with a prefix
  - sentinel values represent missing active transaction
  - timestamps participate in canonical selection
- update tests to assert:
  - monotonic session issuance
  - monotonic transaction issuance
  - continued monotonic event sequencing
  - parent-child session/transaction/event relationships
  - exact identity matching
  - compatibility replay for historical legacy IDs
- add malformed metadata tests
- add parent-log consistency tests

**Deliverables**
- updated regression tests
- compatibility tests
- parent-log consistency coverage
- issuance metadata validation coverage

**Acceptance for phase**
- new tests assert the session / transaction / event hierarchy
- legacy replay compatibility is covered
- malformed metadata behavior is covered
- parent-log consistency is covered

---

### Phase 7: Update documentation and contract-facing guidance
**Goals**
- Make the new identity model explicit for future implementation and debugging work.

**Tasks**
- update docs to explain:
  - `session_id` role
  - `tx_id` role
  - `seq` role
  - `ticket_id` role
  - timestamp limitations
  - parent logs vs event log
- update guidance around deterministic recovery
- document whether `event_id` is optional compatibility metadata or removed from future expectations
- update operational guidance to reflect the new server-managed identity model

**Deliverables**
- updated implementation docs
- updated contract-facing guidance
- updated operator/debugging guidance

**Acceptance for phase**
- a reader can understand the complete identity model without reading source code
- the hierarchy and recovery rules are documented in one place
- timestamp policy is explicit

## Recommended Ticket Breakdown

### Phase 1
- `p1-t01`: Define the session / transaction / event identity contract
- `p1-t02`: Define parent-log schemas and counter metadata policy
- `p1-t03`: Decide compatibility treatment for `event_id` and legacy identifier formats

### Phase 2
- `p2-t01`: Implement session issuance metadata and monotonic `session_id`
- `p2-t02`: Implement transaction issuance metadata and monotonic `tx_id`

### Phase 3
- `p3-t01`: Introduce `.agent/session_log.jsonl`
- `p3-t02`: Introduce `.agent/tx_log.jsonl`
- `p3-t03`: Define parent-log update rules across lifecycle changes

### Phase 4
- `p4-t01`: Remove ticket-derived transaction ID generation
- `p4-t02`: Remove normal-flow sentinel transaction identity handling
- `p4-t03`: Simplify lifecycle validation to use exact identifiers

### Phase 5
- `p5-t01`: Update active session recovery ordering
- `p5-t02`: Update active transaction recovery ordering
- `p5-t03`: Update rebuild/materialized identity conflict handling

### Phase 6
- `p6-t01`: Add regression coverage for session issuance, transaction issuance, and event ordering
- `p6-t02`: Add compatibility tests for historical legacy IDs
- `p6-t03`: Add parent-log consistency and malformed-metadata tests

### Phase 7
- `p7-t01`: Update docs and contract-facing guidance for the robust identity model

## Risks

### 1. Legacy assumptions are broader than expected
There may be more places than expected that assume:
- `tx_id` contains ticket information
- sentinel values like `none` represent missing active transaction
- timestamps are safe fallback selectors
- event log replay alone must reconstruct all parent-level state

**Mitigation**
- inventory identifier assumptions before implementation
- migrate in phases
- add compatibility tests early

### 2. Parent logs may drift from event history if update rules are unclear
If parent logs are introduced without strict consistency rules, they may drift from the detailed event log.

**Mitigation**
- define clear write/update ordering
- treat parent logs as canonical parent metadata with explicit consistency invariants
- test parent-log consistency directly

### 3. Mixed old/new histories may be confusing
A repository may contain:
- legacy transaction IDs
- newly issued monotonic transaction IDs
- historical events without parent logs
- new events with parent-log support

**Mitigation**
- document compatibility clearly
- preserve replay for historical logs
- keep new-write policy strict

### 4. Timestamp misuse may reappear informally
Even after documentation, recovery logic may drift back toward timestamp-based tie-breaking.

**Mitigation**
- document timestamp limits explicitly
- add tests ensuring identifier-first recovery
- keep timestamps observational only

## Open Questions

### 1. Should counter metadata be separate or unified?
Options:
- separate counter files for sessions and transactions
- unified counter state

Recommendation:
- prefer unified state if implementation remains simple
- otherwise adopt separate session and transaction counter files incrementally

### 2. Should parent logs be append-only or compacted summary records?
This needs a final policy.
The key requirement is deterministic recoverability and consistency with the event log.

### 3. Should `event_id` remain at all?
Recommendation:
- do not require it as a core canonical identifier
- retain only if compatibility or diagnostics still benefit from it

## Acceptance Criteria
0.5.5 is complete when:
- the canonical server-managed identity hierarchy is explicitly defined as session -> transaction -> event
- new sessions receive monotonic issued `session_id` values
- new transactions receive monotonic issued `tx_id` values
- event `seq` remains the canonical detailed event-ordering identity
- timestamps are explicitly non-canonical for ordering and deterministic recovery
- `.agent/session_log.jsonl` exists with a documented canonical role
- `.agent/tx_log.jsonl` exists with a documented canonical role
- `.agent/tx_event_log.jsonl` remains the detailed canonical event history
- new `tx_id` values are no longer derived from `ticket_id`
- normal lifecycle flow does not use `tx_id="none"`
- recovery prefers exact identifiers over timestamp heuristics
- historical logs remain replayable under a documented compatibility policy
- and regression coverage locks the new behavior in place

## Summary
The 0.5.5 plan is no longer only about changing `tx_id`.

It is about establishing a robust canonical identity model for the server:

- `session_id` for runtime session identity
- `tx_id` for concrete transaction identity
- `seq` for event ordering
- `ticket_id` for user-visible work identity
- timestamps for observation only

To support that model, the system should persist:
- a session parent log
- a transaction parent log
- and the existing detailed event log

This should reduce ambiguity, improve deterministic recovery, simplify lifecycle logic, and make the canonical state model more robust in a way that resembles well-structured relational systems, without weakening replay integrity or lifecycle strictness.