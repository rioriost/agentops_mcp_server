# Draft for 0.5.5: redesign canonical identifiers around session, transaction, and event logs

## Background

Version 0.5.4 focused on making canonical workflow guidance more machine-readable and safer for agent-driven lifecycle handling.

That work improved how agents understand:

- canonical status,
- canonical phase,
- next required action,
- follow-up requirements,
- and recovery guidance.

However, recent debugging has exposed a more structural problem beneath the remaining lifecycle failures:

- `tx_id` currently carries too much semantic ambiguity,
- transaction identity is partially entangled with ticket identity,
- some logic treats `tx_id` as opaque,
- some logic compares it to `ticket_id`,
- some paths normalize sentinel values such as `none`,
- and some logic still relies on prefix or substring comparisons around transaction identifiers.

This is a symptom of a deeper modeling issue: the current system records detailed transaction events, but it does not yet model canonical identity layers as explicitly as it should.

In practice, the runtime really has three distinct layers:

1. session
2. transaction
3. event

A robust implementation should treat these as separate concerns, with separate server-managed identifiers and logs.

## Problem

The current identity model is too flat and too overloaded.

Today, transaction and execution context are inferred from a combination of:

- `ticket_id`,
- `tx_id`,
- `session_id`,
- materialized state,
- and replayed event history.

That creates avoidable ambiguity in cases such as:

- begin-versus-resume validation,
- active transaction mismatch detection,
- materialized versus rebuilt active transaction comparison,
- session recovery from `.agent` artifacts,
- duplicate-`tx.begin` protection,
- and handling of non-canonical placeholders such as `none`.

The root issue is that the canonical execution model is hierarchical, but the persistence model does not make that hierarchy explicit enough.

The actual runtime relationship is:

- one session contains multiple transactions,
- one transaction contains multiple events.

Without making that structure explicit in canonical persistence, the system is forced to recover identity from heuristics and partial state.

## Why this matters

The AgentOps model depends on a strict and predictable distinction between:

1. planning identity,
2. execution-session identity,
3. transaction identity,
4. event ordering,
5. materialized state,
6. and replay/recovery behavior.

Those roles weaken when:

- `tx_id` is overloaded,
- `session_id` is not treated as a first-class server-managed identifier,
- and transaction-level metadata is inferred only from event replay.

For resumability to remain dependable, the system should make these roles explicit:

- `ticket_id` identifies a work item,
- `session_id` identifies a runtime session,
- `tx_id` identifies a concrete transaction instance,
- `seq` identifies canonical global event order.

A clearer model should improve:

- lifecycle guard correctness,
- deterministic recovery,
- replay determinism,
- materialized/rebuild consistency,
- and testability.

## Goal

For 0.5.5, redesign canonical identity handling so that the server explicitly manages:

- session identity,
- transaction identity,
- and event ordering

as separate layers.

The redesign should ensure that:

- every new session receives a canonical server-managed `session_id`,
- every new transaction receives a canonical server-managed `tx_id`,
- every event continues to receive a canonical global `seq`,
- transaction identity is no longer derived from `ticket_id`,
- placeholder identifiers such as `none` are eliminated from normal canonical operation,
- and recovery can proceed deterministically using exact identifiers rather than string-shape heuristics.

## Desired outcome

After 0.5.5:

- canonical runtime identity is modeled as session -> transaction -> event,
- `session_id` is server-managed and monotonic,
- `tx_id` is server-managed and monotonic,
- `seq` remains the canonical event-ordering identifier,
- transaction creation uses a single canonical issuance path,
- ticket identity and transaction identity are cleanly separated,
- begin/resume validation no longer depends on `tx-` prefixes or substring matching,
- session recovery prefers exact identity matching,
- and lifecycle behavior becomes easier to reason about for both humans and agents.

## Canonical server-managed identifiers

The planning documents under `docs/` remain client-managed workflow convention.

They are important, but they are not the canonical server protocol.

The canonical server-managed identifiers that matter for execution are:

### 1. `session_id`
Identifies one runtime session.

### 2. `tx_id`
Identifies one concrete transaction instance.

### 3. `seq`
Identifies one canonical event position in the global transaction event log.

## Identity hierarchy

The canonical hierarchy should be:

- one `session_id`
  - many `tx_id`
    - many `seq`-ordered events

This mirrors a relational model such as:

- `sessions`
- `transactions`
- `events`

in a database-backed design.

## Proposed canonical log model

## 1. `session_log.jsonl`
Introduce a session-level canonical log under `.agent/`.

Proposed file:

- `.agent/session_log.jsonl`

This log represents runtime sessions as first-class canonical records.

Suggested record shape:

- `session_id`
- `created_at`
- `updated_at`
- `status`
- `first_tx_id`
- `last_tx_id`
- `last_event_seq`

Its purpose is to make session identity explicit and queryable without reconstructing it only from event-level history.

## 2. `tx_log.jsonl`
Introduce a transaction-level canonical log under `.agent/`.

Proposed file:

- `.agent/tx_log.jsonl`

This log represents transactions as first-class canonical records.

Suggested record shape:

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

This log should act like the canonical parent record for a transaction, while `tx_event_log.jsonl` remains the detailed append-only event history.

## 3. `tx_event_log.jsonl`
Retain:

- `.agent/tx_event_log.jsonl`

This remains the canonical append-only detailed event history.

It should continue to store:

- `seq`
- `tx_id`
- `session_id`
- `event_type`
- `phase`
- `step_id`
- `ts`
- `payload`

The difference after 0.5.5 is that the system should no longer rely on the event log alone to infer all session and transaction metadata.

Instead:

- `session_log.jsonl` is the session parent log,
- `tx_log.jsonl` is the transaction parent log,
- `tx_event_log.jsonl` is the detailed child log.

## Proposed ID model

## 1. Session IDs are monotonic positive integers
A session ID should be issued from a monotonic counter.

The issuance model is:

- initial counter value: `0`
- first issued session ID: `1`
- next issued session IDs: `2`, `3`, `4`, ...

For JSON-facing artifacts, the stored representation may be serialized as a string.

Recommended stored form:

- `"1"`
- `"2"`
- `"3"`

## 2. Transaction IDs are monotonic positive integers
A transaction ID should also be issued from a monotonic counter.

The issuance model is:

- initial counter value: `0`
- first issued transaction ID: `1`
- next issued transaction IDs: `2`, `3`, `4`, ...

For JSON-facing artifacts, the stored representation may be serialized as a string.

Recommended stored form:

- `"1"`
- `"2"`
- `"3"`

## 3. Event sequence remains a monotonic global event counter
The existing event sequence should remain the canonical global event-ordering identifier.

This means:

- `seq` remains append-only,
- `seq` remains globally monotonic,
- and replay order remains `seq` ascending.

This layer already matches the intended model well and should not be fundamentally redesigned in 0.5.5.

## 4. `event_id` is not required
A separate `event_id` is not required for the current file-backed architecture.

The canonical event identifier is already:

- `seq`

A separate `event_id` would add complexity without clear value unless the system later needs:

- distributed append,
- cross-system merge,
- or externally referenced immutable event handles.

For 0.5.5, `seq` should remain sufficient.

## Counter metadata

## 1. Session counter
Introduce session issuance metadata under `.agent/`.

Proposed file:

- `.agent/session_id_counter.json`

Suggested contents:

- `last_issued_id`
- `updated_at`

Example shape:

- `last_issued_id: 3`
- `updated_at: 2026-03-09T12:34:56+00:00`

## 2. Transaction counter
Introduce transaction issuance metadata under `.agent/`.

Proposed file:

- `.agent/tx_id_counter.json`

Suggested contents:

- `last_issued_id`
- `updated_at`

Example shape:

- `last_issued_id: 12`
- `updated_at: 2026-03-09T12:34:56+00:00`

These files are not lifecycle history.

They are issuance metadata only.

Their role is to allocate the next canonical identifier safely and deterministically.

## Issuance rules

## 1. Session issuance
When a new runtime session begins:

1. read `.agent/session_id_counter.json`
2. increment `last_issued_id` by `1`
3. persist the updated counter
4. create a canonical `session_log.jsonl` record for the new `session_id`

No other path should mint a new session identifier.

## 2. Transaction issuance
When a new transaction begins:

1. read `.agent/tx_id_counter.json`
2. increment `last_issued_id` by `1`
3. persist the updated counter
4. create a canonical `tx_log.jsonl` record for the new `tx_id`
5. emit `tx.begin` using that `tx_id`

No other path should mint a new transaction identifier.

In particular:

- resume/update paths must not issue new IDs,
- rebuild/recovery paths must not issue new IDs,
- and helper tools must not synthesize replacement IDs.

## 3. Event issuance
When a new event is appended:

- continue using the existing monotonic global `seq`

No redesign is needed here beyond preserving ordering guarantees.

## Timestamp policy

Timestamps remain useful, but they should not become the canonical ordering key.

### Allowed role for timestamps
Timestamps should be used for:

- observability,
- debugging,
- human-readable chronology,
- and sanity checks.

### Disallowed role for timestamps
Timestamps should not become the primary determinant of canonical ordering or deterministic recovery.

Ordering should remain driven by canonical identifiers:

- `session_id`
- `tx_id`
- `seq`

This follows robust database design more closely than timestamp-first ordering.

## Identity roles

## `ticket_id`
Represents the work item, release-scoped task label, or user-visible workflow identifier.

It is not the canonical runtime transaction identifier.

## `session_id`
Represents one runtime session only.

It is the canonical parent identifier for transactions created in that session.

## `tx_id`
Represents one concrete transaction instance only.

It is the canonical parent identifier for transaction events.

## `seq`
Represents canonical append order of events globally.

It is the canonical event-ordering identifier.

## Normal-state rules

The normal canonical runtime state should behave like this:

- before a session exists: no active `session_id`
- after session start: valid issued `session_id`
- before `tx.begin`: no active `tx_id`
- after `tx.begin`: valid issued `tx_id`
- during lifecycle progression: all related events reuse the same `tx_id`
- event order is always determined by `seq`

Sentinel values such as:

- `none`
- empty pseudo-identifiers used as placeholders
- prefix-based synthetic transaction labels

should not be used as normal canonical identifiers.

## Why this design is better

## A. Clearer hierarchy
The system becomes structurally explicit:

- session parent
- transaction parent
- event child

This is easier to reason about and more robust than inferring everything from event replay alone.

## B. Simpler lifecycle validation
With monotonic issued IDs:

- active transaction existence becomes a direct state question,
- not a string-shape question.

Begin/resume logic can simplify to checks like:

- does an active session exist?
- does an active non-terminal transaction exist?
- does it already have an issued `tx_id`?
- does the requested `ticket_id` match the active ticket?

instead of comparing:

- prefixed IDs,
- normalized strings,
- or partial textual relationships.

## C. Cleaner rebuild semantics
Replay and rebuild should treat:

- `session_id` as an opaque issued identifier,
- `tx_id` as an opaque issued identifier,
- `seq` as canonical order.

That makes conflict checks more reliable because rebuild logic no longer needs to infer meaning from string contents.

## D. Better session recovery
Session recovery should prefer exact canonical identity.

With explicit session and transaction parent logs, recovery can prioritize:

1. explicit `session_id`
2. exact session match from `session_log.jsonl`
3. exact transaction match from `tx_log.jsonl`
4. exact event-derived fallback from `tx_event_log.jsonl`
5. bounded artifact fallback
6. failure if recovery is ambiguous

This is much safer than mixed prefix/substring comparisons.

## E. More robust testing
Tests become easier to write and maintain because they no longer need to encode assumptions such as:

- `tx_id` starts with `tx-`
- `tx_id` embeds `ticket_id`
- string prefixes imply transaction lineage

Instead, tests can assert:

- session issuance order,
- transaction issuance order,
- event sequence order,
- exact identity matching,
- and explicit parent-child relations.

## Scope

### In scope

- defining canonical server-managed identifiers explicitly,
- adding `.agent/session_log.jsonl`,
- adding `.agent/tx_log.jsonl`,
- adding `.agent/session_id_counter.json`,
- adding `.agent/tx_id_counter.json`,
- changing new session creation to use issued session IDs,
- changing new transaction creation to use issued transaction IDs,
- removing `ticket_id`-derived transaction ID generation,
- eliminating sentinel identifier values from normal canonical flow,
- simplifying lifecycle comparisons that depend on identifier shape,
- updating recovery logic to prefer exact session/transaction identity,
- and updating tests and documentation to reflect the new canonical identifier model.

### Out of scope

- redesigning ticket identifiers,
- changing the event taxonomy,
- weakening lifecycle ordering rules,
- weakening replay integrity validation,
- rewriting existing historical logs in place,
- or replacing the transaction log with a different persistence model.

## Non-goals

This draft does not propose:

- making identifiers globally meaningful beyond repository-local canonical state,
- allowing multiple issuance strategies,
- preserving legacy string-derived transaction ID formats for new writes,
- or silently accepting malformed historical identity records as healthy canonical state.

The goal is simplification and correctness, not format pluralism.

## Compatibility policy

## Existing historical logs
Historical repositories may already contain:

- legacy `tx_id` values,
- legacy session handling assumptions,
- and historical event records that predate the new layered identity model.

0.5.5 should define a clear compatibility policy for those cases.

Recommended policy:

- historical logs remain readable,
- historical legacy `tx_id` values remain replayable as opaque identifiers,
- historical event logs remain canonical detailed history,
- but all newly issued `session_id` and `tx_id` values use the new monotonic scheme.

This allows forward migration without rewriting historical event logs.

## New writes
All new canonical writes after 0.5.5 should use the new layered identity model.

That means:

- no new code path should emit `tx_id` derived from `ticket_id`
- no new code path should emit sentinel identifiers such as `none`
- new sessions should use issued monotonic `session_id`
- new transactions should use issued monotonic `tx_id`
- new events should continue to use monotonic global `seq`

## Proposed implementation changes

## A. Add canonical session log storage
Introduce:

- `.agent/session_log.jsonl`

Responsibilities:

- create canonical session parent records,
- record session lifecycle metadata,
- support deterministic recovery,
- support session-to-transaction navigation.

## B. Add canonical transaction log storage
Introduce:

- `.agent/tx_log.jsonl`

Responsibilities:

- create canonical transaction parent records,
- record transaction lifecycle metadata,
- support active transaction lookup,
- support deterministic recovery,
- support transaction-to-event navigation.

## C. Retain and clarify canonical event log behavior
Retain:

- `.agent/tx_event_log.jsonl`

Responsibilities remain:

- append-only detailed event history,
- canonical replay source,
- global event ordering via `seq`.

## D. Add canonical identifier issuance metadata
Introduce:

- `.agent/session_id_counter.json`
- `.agent/tx_id_counter.json`

Responsibilities:

- initialize if missing,
- validate shape,
- return the next issued identifier,
- persist the updated counter with timestamp.

Suggested behavior:

- missing counter file may be treated as zero baseline for issuance metadata only,
- malformed counter file should be treated as a configuration/integrity failure, not as zero.

## E. Replace ticket-derived transaction ID generation
Current transaction ID generation should be replaced with issuance from the monotonic transaction counter.

Any helper currently responsible for generating transaction IDs from `ticket_id` should instead request the next issued transaction ID.

## F. Simplify lifecycle comparison logic
The following classes of logic should be simplified or removed:

- `tx-` prefix stripping,
- substring comparisons between `ticket_id` and `tx_id`,
- sentinel handling around `"none"`,
- and heuristics that infer identity from textual shape.

Comparison policy should become:

- exact `session_id` match when session identity is available,
- exact `tx_id` match when transaction identity is available,
- exact `ticket_id` match only where ticket identity is the intended comparison,
- and explicit begin-required behavior when no valid canonical transaction identity exists.

## G. Clarify deterministic recovery ordering
Recovery should prefer canonical identifiers over timestamps.

Recommended order:

1. explicit `session_id`
2. exact canonical `session_id` match from `session_log.jsonl`
3. exact canonical `tx_id` match from `tx_log.jsonl`
4. exact replay-derived event match from `tx_event_log.jsonl`
5. bounded artifact fallback
6. failure if ambiguous

Timestamps may remain useful for observability, but not as the primary determinant of canonical ordering.

## H. Add regression coverage
Regression coverage should include at least:

- first session issuance from zero baseline,
- monotonic increment across multiple sessions,
- first transaction issuance from zero baseline,
- monotonic increment across multiple transactions,
- persistence of the last issued session and transaction IDs,
- begin flow using newly issued transaction IDs,
- no issuance during resume/update/end flows,
- exact active transaction matching with monotonic IDs,
- exact session recovery using canonical session identity,
- compatibility with legacy historical transaction IDs during replay,
- compatibility with historical event logs during migration,
- and rejection of malformed counter metadata.

## Open design questions

## 1. String or numeric JSON representation?
The recommended approach is:

- numeric issuance semantics,
- string serialization in JSON-facing artifacts.

This minimizes disruption while preserving clarity.

If the implementation prefers numeric JSON storage everywhere, that is possible, but it should be applied consistently.

## 2. Separate counter files or unified counter file?
Two viable approaches exist:

### Separate files
- `.agent/session_id_counter.json`
- `.agent/tx_id_counter.json`

### Unified file
- `.agent/id_counters.json`

A unified file may be more database-like and easier to checkpoint, but separate files may be simpler to implement incrementally.

## 3. Should session logs record closure explicitly?
A robust design probably should.

For example, session status could distinguish:

- active
- closed
- abandoned

This would improve recovery and observability.

## 4. Should the system expose compatibility diagnostics when replaying legacy identifiers?
This is optional, but it may be useful for observability and debugging while old and new identifier formats coexist during migration.

## Acceptance criteria

0.5.5 should be considered complete when:

- canonical runtime identity is explicitly modeled as session -> transaction -> event,
- new `session_id` values are issued from a monotonic counter,
- new `tx_id` values are issued from a monotonic counter,
- `seq` remains the canonical monotonic event-ordering identifier,
- `.agent/session_log.jsonl` exists and records canonical session metadata,
- `.agent/tx_log.jsonl` exists and records canonical transaction metadata,
- no new transaction IDs are derived from `ticket_id`,
- sentinel identifiers such as `none` are no longer part of normal canonical lifecycle operation,
- begin/resume validation no longer depends on prefix or substring heuristics,
- session and transaction recovery prefer exact canonical identity,
- timestamps are treated as observability metadata rather than primary recovery order,
- legacy event logs remain replayable under documented compatibility rules,
- and regression coverage locks the new layered identifier model in place.

## Summary

The core proposal for 0.5.5 is to make canonical runtime identity explicit and layered:

- introduce canonical session identity,
- introduce canonical transaction identity,
- retain canonical event ordering,
- persist parent logs for sessions and transactions,
- separate runtime identity from planning identity,
- and simplify lifecycle logic accordingly.

This change does not weaken the canonical lifecycle model.

Instead, it makes identity handling more robust, more database-like, and easier to reason about, which should directly improve resumability, rebuild correctness, and agent reliability.