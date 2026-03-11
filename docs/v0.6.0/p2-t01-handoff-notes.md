# p2-t01 Handoff Notes for Later Tickets

## Purpose
This note records the `p2-t01`-specific findings that should be carried forward into later phase-2 tickets without expanding `p2-t01` beyond its intended scope.

This document is a derived implementation note.
It does not add canonical requirements beyond:

- `docs/v0.6.0/plan.md`
- `docs/v0.6.0/p2-t01.json`
- `docs/v0.6.0/ops-tool-contract-alignment-plan.md`

---

## p2-t01 scope boundary reminder

`p2-t01` is limited to identity-allocation strictness for new writes.

The relevant enforced boundary is:

- no new write path derives `tx_id` from `ticket_id`
- no new write path derives `tx_id` from `task_id`
- issued `tx_id` allocation occurs only through canonical begin
- issued `tx_id` values remain integer-valued in JSON-facing artifacts
- compatibility behavior must not weaken strict new-write semantics

This means `p2-t01` is **not** the ticket for broad helper-contract redesign, broad resume simplification, or broad bounded-compatibility redesign.

---

## Summary of current p2-t01 review outcome

During `p2-t01` review, two follow-up concerns were identified in runtime code.

They were reviewed against later ticket scopes and determined to belong to later tickets rather than `p2-t01`.

### Concern 1: helper input and canonical identity boundary mixing in `ops_tools.py`
Observed concern:
- helper-facing identifiers such as `task_id` and `ticket_id` still participate in resume-facing helper behavior
- helper behavior around active transaction lookup is not yet the cleanest possible separation between client-managed labels and canonical runtime identity

Why this was **not** expanded into `p2-t01`:
- the current concern is primarily about exact-resume helper behavior and helper-contract alignment
- it is not, by itself, evidence that new write paths are deriving new `tx_id` values from `ticket_id`
- `p2-t01` should stay focused on issued identity allocation and strict new-write semantics

Assigned follow-up ticket:
- `p2-t03`

Secondary relevance:
- `p2-t04`

### Concern 2: helper bootstrap / `tx.begin` backfill behavior in `commit_manager.py`
Observed concern:
- helper behavior may backfill or bootstrap `tx.begin` under bounded conditions
- this can blur external visibility of canonical lifecycle ordering and should be reviewed for explicitness and boundedness

Why this was **not** expanded into `p2-t01`:
- the concern is about helper bootstrap semantics, exact continuation, and compatibility boundaries
- it is not direct evidence of ticket-derived `tx_id` issuance
- `p2-t01` should not absorb broader helper-orchestration redesign

Assigned follow-up tickets:
- `p2-t03`
- `p2-t04`

---

## Handoff to `p2-t03`

### Why `p2-t03` owns this
`p2-t03` is the ticket for:
- exact active transaction continuation
- next_action-first continuation
- avoiding heuristic replacement of active work
- aligning `ops_*` helper contracts with exact-active-transaction behavior

### `p2-t03` should explicitly re-check
1. `ops_tools.py`
   - confirm helper-facing inputs do not blur exact active-transaction continuation semantics
   - confirm resume behavior prefers the exact active transaction and valid canonical `next_action`
   - confirm helper convenience does not substitute label-based selection for exact canonical continuation

2. `commit_manager.py`
   - confirm helper bootstrap behavior does not hide canonical lifecycle ordering more than the accepted transition strategy allows
   - confirm any begin backfill behavior remains exact-identity-preserving and non-heuristic
   - confirm existing active transaction identity is reused exactly rather than reinterpreted through helper labels

3. responses and operator guidance
   - confirm responses make continuation state and follow-up actions explicit
   - confirm helper behavior does not weaken the protocol distinction between begin, continuation, commit, and explicit terminal completion

### `p2-t03` implementation warning
Do **not** reinterpret this handoff note as permission to change `tx_id` issuance semantics.
That remains out of scope for `p2-t03` and belongs to `p2-t01`.

---

## Handoff to `p2-t04`

### Why `p2-t04` owns this
`p2-t04` is the ticket for:
- session context as secondary, not primary, correctness context
- bounded historical compatibility behavior
- explicit handling of ambiguous or malformed persistence
- bounded helper-context recovery without promoting helper inputs into canonical identity

### `p2-t04` should explicitly re-check
1. `ops_tools.py`
   - confirm helper recovery paths do not promote `session_id`, `task_id`, or other helper context into canonical runtime identity
   - confirm recovery remains bounded, deterministic, and explicit on ambiguity
   - confirm helper-context recovery does not displace canonical continuation rules

2. `commit_manager.py`
   - confirm helper bootstrap / backfill behavior is treated as bounded compatibility behavior rather than silent protocol rewriting
   - confirm compatibility handling does not weaken strict new semantics introduced by issued canonical `tx_id`
   - confirm malformed or ambiguous recovery paths fail clearly rather than silently normalizing into healthy state

3. compatibility-facing guidance
   - confirm user-facing and machine-readable guidance distinguishes bounded helper recovery from canonical identity rules
   - confirm compatibility logic remains subordinate to canonical transaction state

### `p2-t04` implementation warning
Do **not** use compatibility or recovery logic to:
- derive a new `tx_id` from `ticket_id`
- derive a new `tx_id` from `task_id`
- treat helper labels as canonical transaction identity

---

## Non-goals for later readers
This note does **not** claim that the current implementation is already fully aligned with:
- explicit begin-vs-lifecycle separation
- final helper-contract shape for `ops_*`
- final bounded-compatibility policy shape

It only records that these concerns were reviewed during `p2-t01` and intentionally deferred because they belong to later tickets.

---

## Recommended usage in later tickets
When working `p2-t03` or `p2-t04`, read this note together with:

- `docs/v0.6.0/p2-t03.json`
- `docs/v0.6.0/p2-t04.json`
- `docs/v0.6.0/ops-tool-contract-alignment-plan.md`
- `docs/v0.6.0/phase0-implementation-map.md`

Use this note as:
- a scope-boundary reminder
- a deferred-concerns checklist
- a guard against reopening `p2-t01` identity-allocation work unnecessarily

---

## Short traceability summary
- `p2-t01` reviewed identity-allocation strictness
- helper-boundary mixing concerns were identified
- helper-bootstrap / backfill concerns were identified
- those concerns map to `p2-t03` exact-resume work and `p2-t04` bounded-compatibility work
- they were intentionally **not** expanded into `p2-t01`
