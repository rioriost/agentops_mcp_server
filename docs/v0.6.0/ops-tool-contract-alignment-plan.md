# 0.6.0 Implementation Plan: Align `ops_*` Tool Contracts with the Canonical Resumable Transaction Protocol

## Status
- **Artifact type**: implementation-phase planning note
- **Canonical source**: `docs/v0.6.0/plan.md`
- **Related evidence**: `docs/v0.6.0/phase0-implementation-map.md`
- **Related framework**: `docs/v0.6.0/traceability-framework.md`
- **Authority rule**: this document is a derived implementation-planning artifact and does not add canonical requirements beyond `plan.md`

## Purpose
This document captures the implementation-phase plan for aligning `ops_*` MCP tool contracts with the `0.6.0` canonical resumable transaction protocol.

It exists to guide implementation work around:
- schema and runtime-validation consistency
- bounded server-side recovery for helper context
- strict protection of canonical identity and lifecycle ordering
- structured machine-readable failure responses
- removal or clarification of helper behaviors that blur canonical protocol boundaries

This artifact is intended for implementation planning and review. It is not itself a replacement for `plan.md`.

---

## 1. Problem statement

Current `ops_*` tool behavior shows contract ambiguity in several places:

- some tool schemas expose broad `string` inputs while runtime validation accepts only narrower value sets
- some helper inputs appear optional at the schema level but may still fail at runtime if recovery is not possible
- some helper behaviors bootstrap or infer protocol steps in ways that reduce the external visibility of canonical lifecycle ordering
- some failures are returned as plain text errors rather than machine-readable workflow guidance

These issues matter because `0.6.0` is explicitly redesigning the work loop as a **resumable transaction protocol**. If tool contracts are looser than runtime semantics, agents and clients can produce invalid inputs too easily, and recovery behavior becomes less deterministic than intended.

---

## 2. Canonical source constraints from `plan.md`

The implementation plan in this document is constrained by the following canonical rules from `docs/v0.6.0/plan.md`:

### 2.1 Identity model constraints
- `ticket_id` is client-managed planning identity
- `tx_id` is server-managed runtime execution identity
- `tx_id` must not be derived from `ticket_id`, `task_id`, or similar helper labels
- `session_id` is secondary runtime context, not canonical transaction identity
- `seq` remains canonical append ordering for transaction events

### 2.2 Resume and continuation constraints
- resume must continue the exact active transaction
- healthy materialized state is the primary resume entrypoint
- `next_action` is the primary continuation guide
- resume must not depend on heuristic replacement of the active transaction
- malformed or ambiguous canonical persistence should fail clearly

### 2.3 Lifecycle constraints
- `tx.begin` creates a transaction
- lifecycle progression must preserve strict ordering
- verify and commit are resumable checkpoints
- commit is non-terminal
- terminal completion is explicit
- `done` is the only successful terminal outcome

### 2.4 Boundary constraints
- server-owned canonical protocol state must remain distinct from client-managed inputs
- helper or observability fields must not redefine canonical transaction identity or correctness
- planning artifacts under `docs/` remain derived rather than canonical runtime truth

---

## 3. Core alignment goal

The goal of this implementation work is:

> make `ops_*` tool contracts explicit enough that clients can call them correctly, while ensuring the server continues to enforce the `0.6.0` canonical transaction protocol even when helper inputs are omitted, invalid, or ambiguous.

This means the design must distinguish between:

- values the server may safely recover
- values the server must reject if absent or invalid
- values that are secondary or advisory only

---

## 4. Contract classification model

For implementation purposes, tool inputs should be grouped into three classes.

## 4.1 Class A: canonical protocol fields
These fields must never be guessed or silently repaired when doing so would affect canonical correctness.

Examples:
- `tx_id`
- active transaction identity
- lifecycle checkpoint ordering
- verify / commit / end semantics
- file-intent transition correctness

### Required behavior
- no heuristic inference
- no silent substitution
- explicit failure if missing, invalid, ambiguous, or out of order

## 4.2 Class B: deterministic helper context
These fields are not canonical identity, but may still matter for continuity, observability, or helper execution.

Examples:
- `session_id`
- `task_id`
- active-step helper context

### Required behavior
- may be recovered by the server when recovery is deterministic and unambiguous
- must fail explicitly when recovery is ambiguous or unavailable
- must not be promoted into canonical identity

## 4.3 Class C: advisory metadata
These fields support observability or operator-facing context but are not required for canonical correctness.

Examples:
- `agent_id`
- some human-facing notes
- some summaries or descriptive helper fields

### Required behavior
- may be null or omitted where appropriate
- should not block canonical continuation unless the specific tool contract truly requires them

---

## 5. Target contract rules for `session_id`

## 5.1 Canonical interpretation
For `0.6.0`, `session_id` is secondary context only. It may support:
- observability
- correlation
- handoff continuity
- helper-call continuity

It must not define:
- active transaction identity
- active transaction selection
- deterministic resume correctness

## 5.2 Target tool behavior
For `ops_*` lifecycle and file-intent tools:
- `session_id` may be provided explicitly
- if omitted, the server may attempt recovery from the active transaction context and relevant `.agent` artifacts
- recovery must succeed only when a unique, deterministic session context is available
- if recovery is ambiguous, the tool must fail explicitly

## 5.3 Disallowed behavior
- selecting one session candidate from multiple possible candidates without explicit input
- treating lack of `session_id` as justification to create a new transaction identity
- using `session_id` as the primary basis for active transaction selection

## 5.4 Implementation consequence
The schema may keep `session_id` nullable or optional, but the tool description and runtime failure contract must clearly state:
- omitted values may be recovered only when unambiguous
- ambiguous recovery is an explicit recoverable failure

---

## 6. Target contract rules for `task_id`

## 6.1 Canonical interpretation
`task_id` is not canonical runtime identity for `0.6.0`. It is a helper-facing or compatibility-facing label.

## 6.2 Target tool behavior
- if omitted and there is one exact active transaction, the server may derive the effective task label from the active transaction context
- `task_id` may be echoed in responses for compatibility and user clarity

## 6.3 Disallowed behavior
- deriving `tx_id` from `task_id`
- reverse-mapping helper labels into canonical runtime identity by heuristic logic
- selecting the active transaction by `task_id` when exact canonical active transaction state already exists

---

## 7. Target contract rules for `ops_start_task`

## 7.1 Current alignment risk
A helper that starts task lifecycle progress while also implicitly creating a transaction can blur the boundary between:
- `tx.begin`
- lifecycle entry
- resumable continuation state

That makes canonical ordering less externally visible.

## 7.2 Preferred `0.6.0` direction
The cleanest protocol design is:
- begin is explicit
- lifecycle tools operate on an already active transaction
- helper wrappers do not hide canonical checkpoint creation

## 7.3 Acceptable transition strategy
If bootstrap behavior is temporarily retained for compatibility:
- the tool must explicitly report that bootstrap occurred
- the response should clearly indicate that both begin and lifecycle entry were emitted
- no hidden identity synthesis may occur

## 7.4 Long-term implementation target
Prefer separating:
- transaction creation / `tx.begin`
from
- task lifecycle progression

This best matches the `0.6.0` goal of a simple, explicit resumable transaction protocol.

---

## 8. Target contract rules for file intent tools

## 8.1 Why file intent tools require strictness
File-intent progression participates in ordered workflow behavior and must not be treated as free-form metadata.

The relevant constraints include:
- file intent registration before mutation
- valid state progression
- verified state only after appropriate verification checkpoint behavior
- update only after prior registration

## 8.2 `ops_add_file_intent.operation`
### Target contract
The accepted operation set should be explicit and finite.

Recommended initial set:
- `create`
- `modify`
- `delete`

If additional values such as move or rename are supported, they must be documented explicitly rather than inferred from generic strings.

### Disallowed behavior
- accepting arbitrary strings and rejecting them only deep in runtime logic
- auto-converting unsupported values into guessed canonical operations

## 8.3 `ops_update_file_intent.state`
### Target contract
The accepted state set should be explicit and finite.

Recommended current set, matching observed runtime expectations:
- `started`
- `applied`
- `verified`

### Disallowed behavior
- free-form strings
- auto-promotion from one state to another
- inferring `verified` when verification ordering has not been satisfied

## 8.4 Ordering enforcement
Target runtime checks should include:
- update requires a previously registered file intent
- `verified` requires prior verification success in the canonical flow
- invalid or out-of-order transitions must fail explicitly

---

## 9. Schema alignment plan

## 9.1 Goal
Bring tool schemas closer to true runtime contracts so invalid inputs are rejected earlier and calling behavior is more self-explanatory.

## 9.2 Planned schema changes
### `ops_add_file_intent`
- constrain `operation` to an explicit enum
- keep `path` and `purpose` required
- document that omitted helper context may be recovered only when unambiguous

### `ops_update_file_intent`
- constrain `state` to an explicit enum
- document ordering preconditions and registration requirement

### `ops_update_task`
- constrain `status` to non-terminal lifecycle values only:
  - `in-progress`
  - `checking`
  - `verified`
  - `committed`
- document that terminal states must use `ops_end_task`

### `ops_end_task`
- constrain `status` to:
  - `done`
  - `blocked`

### lifecycle tool descriptions
For each lifecycle-related tool, document:
- whether active transaction context is required
- whether omitted helper fields may be recovered
- what kinds of ambiguity cause explicit failure

---

## 10. Machine-readable failure plan

## 10.1 Goal
Failures should be actionable by agents and clients without relying on prose interpretation.

## 10.2 Standard failure fields
Where possible, failure responses should include:
- `ok: false`
- `error_code`
- `reason`
- `field` when relevant
- `expected` for enum or contract violations
- `recoverable`
- `recommended_next_tool`
- `recommended_action`
- `canonical_status`
- `canonical_phase`
- `next_action`
- `active_tx_id`
- `active_ticket_id`
- `integrity_status`
- `blocked`

## 10.3 Representative failure cases
### invalid file intent operation
- `error_code: invalid_file_intent_operation`
- `field: operation`
- `expected: ["create", "modify", "delete"]`
- `recoverable: true`

### invalid file intent state
- `error_code: invalid_file_intent_state`
- `field: state`
- `expected: ["started", "applied", "verified"]`
- `recoverable: true`

### ambiguous session recovery
- `error_code: ambiguous_session_context`
- `recoverable: true`
- `recommended_action: provide session_id explicitly`

### lifecycle ordering violation
- `error_code: lifecycle_order_violation`
- `recoverable` depends on context
- `recommended_action` should name the missing prerequisite checkpoint

---

## 11. Compatibility and migration stance

## 11.1 Compatibility principle
`0.6.0` allows bounded compatibility for historical data and helper behavior, but not at the cost of weakening canonical correctness.

## 11.2 Contract migration goal
The migration path should:
- reduce schema ambiguity
- preserve deterministic recovery where it is already valid
- remove hidden heuristic behavior where it affects canonical semantics
- avoid breaking historical readability while tightening new normal-flow semantics

## 11.3 Explicit non-goal
This work must not:
- promote helper identifiers into canonical identity
- treat convenience recovery as permission for heuristic transaction selection
- reinterpret malformed canonical state as healthy state

---

## 12. Proposed implementation work breakdown

## 12.1 Contract inventory and gap review
Review and compare, for each `ops_*` tool:
- schema contract
- runtime validation
- workflow response behavior
- `plan.md` alignment
- `.rules` alignment

Expected output:
- a mismatch matrix
- a list of fields that need enum constraints
- a list of fields that are recoverable versus strict

## 12.2 Schema hardening
Update tool schemas to reflect real contract expectations.

Expected output:
- enum constraints for file intent and lifecycle status fields
- improved descriptions for recovery and ambiguity behavior

## 12.3 Runtime validation hardening
Update runtime validation and recovery logic to enforce the intended boundaries.

Expected output:
- bounded recovery for helper context only
- explicit failures for canonical ambiguity
- clearer begin/lifecycle separation behavior

## 12.4 Structured error response work
Standardize common failure cases into machine-readable response shapes.

Expected output:
- reusable error construction patterns
- normalized error codes for common contract failures

## 12.5 Regression coverage
Add tests that prove contract behavior remains deterministic.

Expected coverage areas:
- omitted `session_id` with unique recovery
- omitted `session_id` with ambiguous recovery
- invalid file-intent operation
- invalid file-intent state
- unregistered file-intent update
- lifecycle ordering violations
- explicit terminal-only handling
- begin/bootstrap clarity behavior

## 12.6 Guidance updates
Update operator and developer guidance once runtime behavior is aligned.

Expected output:
- contract-aware usage guidance
- examples of recoverable versus non-recoverable failures
- guidance for clients calling lifecycle and file-intent helpers

---

## 13. Suggested ticket mapping

This implementation plan most directly supports the following `0.6.0` tickets.

### Primary relevance
- `p1-t01`
  - identity boundary between canonical runtime state and helper/client inputs
- `p1-t02`
  - lifecycle ordering and continuation semantics
- `p2-t03`
  - exact active-transaction continuation
- `p2-t04`
  - bounded session-context role and compatibility
- `p3-t03`
  - operator and developer guidance

### Secondary relevance
- `p1-t03`
  - malformed versus missing behavior and persistence/recovery implications

This mapping is for implementation planning only. It does not redefine ticket scope beyond `plan.md`.

---

## 14. Acceptance checks for this planning artifact

This planning artifact is useful only if all of the following are true:
- it remains derived from `plan.md`
- it does not redefine canonical transaction semantics
- it clearly separates strict canonical fields from recoverable helper context
- it gives implementers a concrete plan for schema, validation, recovery, and error-shape alignment
- it identifies where convenience behavior must be clarified or constrained rather than silently preserved

---

## 15. Summary

The `0.6.0`-correct direction for `ops_*` tool contracts is:

- keep canonical protocol correctness strict
- recover helper context only when recovery is deterministic and unambiguous
- never recover canonical identity by heuristic means
- make schemas reflect real runtime contracts
- return machine-readable failure responses that support deterministic client repair
- clarify or separate helper behaviors that currently hide canonical checkpoints

This alignment work is part of the `0.6.0` redesign itself, not a separate usability improvement outside scope.