# p1-t01 Specification: Canonical Resumable Work Transaction Model

## Status
- **Ticket**: `p1-t01`
- **Title**: Define the canonical resumable work transaction model
- **Canonical source**: `docs/v0.6.0/plan.md`
- **Source plan phase**: `Implementation Strategy / Phase 1`
- **Derived artifact type**: implementation-facing specification
- **Authority rule**: this document is derived from `plan.md` and must not add canonical requirements beyond it

## Purpose
This artifact translates the plan-defined transaction meaning, lifecycle semantics, active-transaction invariants, and identity roles into implementation-facing specification language for `p1-t01`.

It exists to support later implementation and verification work by:
- restating the plan-defined transaction model in implementation-oriented form
- making the identity boundary explicit between canonical runtime state and client-managed helper inputs
- providing traceable review targets for runtime code
- separating canonical requirements from current-code observations and downstream work planning

This document is not a replacement for `docs/v0.6.0/plan.md`. When wording here appears narrower or broader than the plan, the plan remains authoritative.

---

## Scope of this ticket
This ticket covers only the requirements allocated to `p1-t01`:

- `REQ-P1-SEMANTICS`
- `REQ-P1-IDENTITY`

This ticket does **not** define:
- the full canonical state machine contract in detail beyond what is needed for semantic interpretation
- persistence schema details allocated to `p1-t03`
- state-machine continuation rules allocated to `p1-t02`
- runtime code changes

---

## Canonical source sections used
The following `plan.md` sections are the canonical sources for this artifact:

- `Canonical Runtime Model`
- `Server-owned transaction variables vs client-managed inputs`
- `Transaction Semantics`
- `Canonical Invariants`
- `Identity Model`
- `Implementation Strategy`

Supporting evidence inputs used for implementation targeting, but not as canonical requirement sources:

- `docs/v0.6.0/phase0-implementation-map.md`
- `docs/v0.6.0/ops-tool-contract-alignment-plan.md`

---

## 1. Canonical meaning of a transaction

## 1.1 What a transaction is
For `0.6.0`, a transaction is:

- a durable ticket-scoped work attempt
- a resumable execution context
- a protocol instance that advances through explicit lifecycle checkpoints until terminal completion

A transaction is therefore the canonical unit of resumable work in the workspace.

## 1.2 What a transaction is not
A transaction is **not**:

- a planning identifier
- a synonym for a ticket
- a row-update batch or generic ACID abstraction
- a successful verify result
- a successful repository commit
- a heuristic reconstruction target that may be replaced during resume

## 1.3 Operational purpose
The plan defines the purpose of a transaction as enabling the system to:

- start work on a ticket
- record progress durably
- survive interruption
- resume deterministically
- verify safely
- commit if appropriate
- terminate explicitly as `done` or `blocked`

## 1.4 One transaction equals one execution attempt
A transaction represents one concrete durable execution attempt for one ticket.

Consequences:
- a ticket may have zero transactions
- a ticket may have one active transaction
- a ticket may have multiple historical transactions over time
- resume must continue the same transaction instance rather than create a replacement attempt

---

## 2. Canonical success model

## 2.1 Successful outcome
The only successful terminal transaction outcome is:

- explicit terminal completion as `done`

## 2.2 What does not count as success
The following are **not** transaction success by themselves:

- verify passed
- commit succeeded

These are checkpoints or intermediate lifecycle results, not terminal success.

## 2.3 Other outcomes
A transaction may also:
- terminate as `blocked`
- remain non-terminal and resumable after failures such as verify failure or commit failure

This preserves the plan-defined distinction between repository state and lifecycle state.

---

## 3. Identity-role contract

## 3.1 `ticket_id`
### Role
`ticket_id` is:
- planning identity
- client-managed workflow label
- input to transaction creation
- useful for human and planning-tool coordination

### Non-role
`ticket_id` is **not**:
- the canonical identity of a running transaction
- the resumable runtime identity
- a valid replacement for `tx_id`

### Review implication
Later runtime implementation must not use `ticket_id` as the canonical runtime execution identifier.

---

## 3.2 `tx_id`
### Role
`tx_id` is:
- the canonical runtime transaction identity
- the identity of one durable execution attempt
- server-managed
- exact and opaque once issued
- reused on resume of the active transaction

### Required semantics
`tx_id`:
- must never be derived from `ticket_id`
- must never be derived from `task_id`
- must not be synthesized from client-managed labels
- must remain the identity anchor for exact resume

### Representation
The plan states that `tx_id` should:
- use monotonic positive integer issuance semantics
- be represented as integers in JSON-facing artifacts

### Review implication
Any new normal-flow logic that infers or reconstructs `tx_id` from helper inputs violates the `0.6.0` identity model.

---

## 3.3 `seq`
### Role
`seq` is:
- canonical append order for transaction events
- the canonical event ordering key
- the chronology key for checkpoint history

### Non-role
`seq` is not replaced by:
- timestamps
- step names
- planning status
- helper metadata

### Review implication
Event ordering logic must anchor on `seq`, not timestamp-first selection or heuristic ordering.

---

## 3.4 `session_id`
### Role
`session_id` is secondary runtime context. The plan allows it to support:
- observability
- correlation
- handoff continuity
- helper-call continuity when needed

### Non-role
`session_id` must not determine:
- active transaction identity
- active transaction selection
- deterministic resume correctness

### Review implication
Later implementation may recover or use `session_id` for bounded helper continuity, but it must never become canonical transaction identity.

---

## 3.5 `task_id`
The plan classifies `task_id` as:
- a helper-API compatibility label
- client-managed
- not part of the canonical `0.6.0` transaction identity model

Therefore:
- `task_id` may exist for helper compatibility
- `task_id` must not be used to infer, reconstruct, or replace `tx_id`

---

## 4. Server-owned versus client-managed boundary

## 4.1 Server-owned canonical continuation state
Within the scope of `p1-t01`, the following belong to the canonical continuation contract because they determine resumability or exact continuation:

- exact active transaction identity
- top-level lifecycle classification
- top-level `next_action`
- verification checkpoint state
- commit checkpoint state
- concise semantic summary
- last materialized event sequence

These are server-owned continuation facts, not client-owned workflow preferences.

## 4.2 Server-owned replay, issuance, and integrity support
The following are server-owned correctness fields:
- `tx_id`
- `seq`
- `event_id` when present
- issuance metadata such as `last_issued_id`
- rebuild and integrity fields such as `rebuilt_from_seq`, `integrity`, `state_hash`, and `drift_detected`

## 4.3 Client-managed inputs and helper labels
The following remain client-managed or helper-facing:
- `ticket_id`
- `task_id`
- `title`
- optional provided `session_id`
- `agent_id`
- `user_intent`
- helper request parameters such as `status`, `note`, `summary`, `path`, `operation`, `purpose`, and tool-control parameters

These values may be persisted or accepted as metadata, but they must not redefine canonical runtime identity or lifecycle truth.

## 4.4 Practical implementation boundary
When reviewing or changing runtime code:
- if a value determines canonical transaction identity, lifecycle ordering, replay integrity, materialized resumability, or issuance state, it is server-owned
- if a value is provided for planning, naming, operator intent, or helper convenience, it is client-managed
- client-managed identifiers must not be promoted into canonical runtime identity by string-shape heuristics, reverse mapping, or replacement synthesis

---

## 5. Canonical invariants in scope for `p1-t01`

## 5.1 Single active transaction
At most one non-terminal active transaction may exist in a workspace.

Required behavior:
- if a non-terminal active transaction exists, it must be resumed first
- no new ticket work may begin while that transaction remains non-terminal
- terminal states are `done` and `blocked`

## 5.2 Begin creates, resume reuses
A new `tx_id` may be created only when starting a new transaction.

Resume must:
- reuse the existing `tx_id`
- preserve the existing transaction identity
- preserve the existing lifecycle context
- never mint a substitute ID

## 5.3 Commit is non-terminal
A successful repository commit does not complete the transaction by itself.

After commit:
- the transaction remains non-terminal
- the transaction may be in `committed`
- explicit terminal completion is still required later

## 5.4 Terminal completion is explicit
Terminal completion must be explicit.

Plan-defined examples:
- `tx.end.done`
- `tx.end.blocked`

## 5.5 Resume is deterministic
Resume must depend on:
- the minimal canonical continuation contract in materialized state
- canonical event history when rebuild is needed
- exact active transaction identity

Resume must not depend on:
- string-shape assumptions
- sentinel transaction identifiers
- timestamp-first selection
- planning-document status as source of runtime truth
- optional phase-style or step-style metadata

---

## 6. Requirement statements for `p1-t01`

## 6.1 `REQ-P1-SEMANTICS`
The canonical transaction semantics for `0.6.0` are:

1. A transaction is one durable execution attempt for one ticket.
2. A transaction is the canonical unit of resumable work.
3. A transaction is a resumable execution context that advances through explicit lifecycle checkpoints until terminal completion.
4. Transaction success means explicit terminal completion as `done`.
5. Verify success alone is not transaction success.
6. Commit success alone is not transaction success.
7. A workspace may have at most one non-terminal active transaction.
8. When a non-terminal active transaction exists, it must be resumed before new ticket work begins.
9. Commit completion is non-terminal and remains separate from explicit terminal completion.
10. Resume must continue the exact active transaction rather than a reconstructed replacement.

## 6.2 `REQ-P1-IDENTITY`
The canonical identity model for `0.6.0` is:

1. `ticket_id` is client-managed planning identity.
2. `ticket_id` is not the canonical identity of a running transaction.
3. `tx_id` is the server-managed identity of one durable execution attempt.
4. `tx_id` is exact and opaque once issued.
5. `tx_id` must not be derived from `ticket_id`, `task_id`, or similar helper labels.
6. Resume must preserve and reuse the exact existing `tx_id`.
7. `seq` remains the canonical append order for transaction events.
8. `session_id` may remain available as secondary context, but it is not part of canonical runtime identity.
9. `task_id` is helper compatibility metadata, not canonical runtime identity.
10. Client-managed identifiers must not be promoted into canonical runtime identity by heuristic inference or replacement synthesis.

---

## 7. Traceability matrix

| Requirement ID | Requirement summary | Canonical source sections | Implementation review targets |
| --- | --- | --- | --- |
| `REQ-P1-SEMANTICS` | Define transaction as a durable, resumable, ticket-scoped execution attempt with explicit terminal success semantics | `Transaction Semantics`; `Canonical Invariants`; `Implementation Strategy` | Lifecycle helper behavior, begin/resume separation, verify/commit/end distinction, operator-facing success semantics, tests that distinguish checkpoint success from terminal success |
| `REQ-P1-IDENTITY` | Distinguish planning identity and helper labels from canonical runtime identity | `Canonical Runtime Model`; `Server-owned transaction variables vs client-managed inputs`; `Identity Model`; `Canonical Invariants`; `Implementation Strategy` | Transaction creation logic, resume logic, active transaction selection, helper APIs, event replay/rebuild identity matching, `ops_*` helper boundary reviews |

---

## 8. Implementation-facing review checklist

## 8.1 Semantics checklist
A later implementation satisfies `p1-t01` semantics only if all of the following are true:

- starting work creates a durable transaction for one ticket
- the transaction is treated as the canonical resumable work unit
- verify success does not by itself mark the transaction successful
- commit success does not by itself mark the transaction successful
- explicit end-of-transaction behavior is required for terminal success
- there is never more than one non-terminal active transaction in the workspace
- begin-new-work is refused or deferred while a non-terminal transaction is active
- resume targets the exact active transaction rather than a replacement candidate

## 8.2 Identity checklist
A later implementation satisfies `p1-t01` identity rules only if all of the following are true:

- `ticket_id` is handled as planning metadata rather than runtime execution identity
- `tx_id` is server-managed and preserved exactly through resume
- no new write path derives `tx_id` from `ticket_id`
- no new write path derives `tx_id` from `task_id`
- event ordering logic uses `seq` as the canonical append order
- session information does not determine active transaction selection
- session information does not redefine deterministic continuation correctness
- helper APIs do not reverse-map client labels into canonical transaction identity in normal flow

## 8.3 `ops_*` helper boundary checklist
When downstream implementation updates `ops_*` helper contracts, the following must remain true:

- helper inputs do not redefine canonical runtime identity
- `task_id` is not promoted into canonical transaction identity
- `session_id` is not promoted into canonical transaction identity
- bounded helper recovery does not become heuristic active-transaction replacement
- helper convenience does not collapse the distinction between begin, continuation, commit, and explicit terminal completion

This checklist is derived support for downstream implementation work. It does not add new canonical requirements beyond the plan.

---

## 9. Gap checklist template for current-code review

This section defines how downstream tickets should compare runtime code against the plan without mixing observation and requirement.

For each relevant runtime module, findings should be labeled as one of:
- **plan-aligned**
- **gap against plan**
- **not in scope for `p1-t01`**

### Required review questions
1. Does any normal-flow logic treat `ticket_id` as running transaction identity?
2. Does any normal-flow logic derive or synthesize `tx_id` from `ticket_id`, `task_id`, string prefixes, or similar heuristics?
3. Does any resume path permit replacing the exact active transaction with a heuristic candidate?
4. Does any flow imply that verify success is terminal success?
5. Does any flow imply that commit success is terminal success?
6. Does any flow allow new work to begin while another non-terminal transaction remains active?
7. Does any correctness-sensitive logic depend on `session_id` beyond bounded secondary context?
8. Do any helper APIs or operator-facing responses blur the distinction between helper labels and canonical runtime identity?

This checklist defines the required review lens. It does not itself answer the questions.

---

## 10. Input consistency check for `p1-t01`

This section verifies that the current `inputs` field for `p1-t01` is complete and non-contradictory relative to the ticket’s purpose.

## 10.1 `docs/v0.6.0/plan.md`
Required and correct.
- It is the canonical source of requirements.
- All normative statements in this artifact derive from it.

## 10.2 `docs/v0.6.0/phase0-implementation-map.md`
Required and correct.
- It is not a canonical requirement source.
- It is an implementation-targeting evidence artifact.
- It helps connect semantics and identity requirements to concrete runtime modules such as `ops_tools.py`, `commit_manager.py`, `state_rebuilder.py`, and `state_store.py`.

## 10.3 `docs/v0.6.0/ops-tool-contract-alignment-plan.md`
Required and correct.
- It is not a canonical requirement source.
- It is a downstream implementation-planning artifact focused on `ops_*` contract alignment.
- It is relevant because `p1-t01` defines the identity boundary that those helper contracts must preserve.

## 10.4 No contradiction check
There is no contradiction among the current inputs because:
- only `plan.md` is treated as canonical
- the other two inputs are explicitly treated as derived evidence/planning artifacts
- no statement in this artifact relies on them to override plan-defined semantics

## 10.5 No missing-input conclusion
For the current scope of `p1-t01`, no additional mandatory input is required.

Reason:
- `p1-t01` is a semantics-and-identity contract ticket
- persistence-contract details belong to `p1-t03`
- detailed continuation/state-machine rules belong to `p1-t02`
- the listed inputs are sufficient to produce the required specification, traceability, and review lens without introducing non-plan requirements

---

## 11. Explicit non-goals
This artifact must not be used to justify any of the following:

- introducing new transaction statuses beyond those defined in `plan.md`
- redefining persistence schema details
- redefining the full state-machine continuation contract
- inventing new compatibility rules outside the plan
- promoting `task_id` or `session_id` into canonical runtime identity
- treating planning artifacts under `docs/` as canonical runtime truth

---

## 12. Acceptance mapping for `p1-t01`

### Acceptance criterion 1
Every requirement in scope is traceable to explicit `plan.md` sections listed in `source_plan_sections`.

Satisfied by:
- `Canonical source sections used`
- `Requirement statements for p1-t01`
- `Traceability matrix`

### Acceptance criterion 2
The ticket artifact does not add canonical requirements that are absent from `plan.md`.

Satisfied by:
- the authority rule in `Status`
- the source discipline in `Canonical source sections used`
- the non-canonical treatment of evidence and planning inputs

### Acceptance criterion 3
The ticket artifact clearly separates plan requirements from current-code observations and future implementation work.

Satisfied by:
- `Gap checklist template for current-code review`
- explicit separation between canonical sections and implementation-facing checklists
- explicit distinction between canonical sources and supporting inputs

### Acceptance criterion 4
The output is detailed enough that later implementation tickets can validate runtime behavior without inventing new semantics.

Satisfied by:
- `Requirement statements for p1-t01`
- `Traceability matrix`
- `Implementation-facing review checklist`
- `Input consistency check for p1-t01`

---

## 13. Summary
`p1-t01` defines the canonical meaning of a transaction for `0.6.0` as one durable, resumable execution attempt for one ticket.

Its core consequences are:

- transaction identity is `tx_id`, not `ticket_id`
- `task_id` and `session_id` are not canonical runtime identity
- only one non-terminal transaction may be active at a time
- resume must continue the exact active transaction
- verify and commit are not terminal success
- terminal success requires explicit completion as `done`

These are the plan-derived identity and semantics rules that downstream implementation tickets must preserve.