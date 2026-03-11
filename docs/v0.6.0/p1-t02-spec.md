# p1-t02 Specification: Canonical State Machine and Continuation Rules

## Status
- **Ticket**: `p1-t02`
- **Title**: Define the canonical state machine and continuation rules
- **Canonical source**: `docs/v0.6.0/plan.md`
- **Source plan phase**: `Implementation Strategy / Phase 1`
- **Derived artifact type**: implementation-facing specification
- **Authority rule**: this document is derived from `plan.md` and must not add canonical requirements beyond it

## Purpose
This artifact translates the plan-defined canonical state machine, continuation rules, `next_action` precedence, and minimal checkpoint event set into implementation-facing specification language for `p1-t02`.

It exists to support later implementation and verification work by:
- restating the plan-defined status model in implementation-oriented form
- making `next_action` precedence explicit
- defining the minimal canonical checkpoint event set and its continuation meaning
- separating canonical requirements from current-code observations and downstream work planning

This document is not a replacement for `docs/v0.6.0/plan.md`. When wording here appears narrower or broader than the plan, the plan remains authoritative.

---

## Scope of this ticket
This ticket covers only the requirements allocated to `p1-t02`:

- `REQ-P1-STATE-MACHINE`
- `REQ-P1-CHECKPOINTS`

This ticket does **not** define:
- transaction identity semantics allocated to `p1-t01`
- persistence, rebuild, or issuance details allocated to `p1-t03`
- runtime code changes
- additional lifecycle states or additional canonical checkpoint events beyond `plan.md`

---

## Canonical source sections used
The following `plan.md` sections are the canonical sources for this artifact:

- `Canonical State Machine`
- `Status set`
- `Meaning of each status`
- `State-machine constraints`
- `Canonical Checkpoints and Events`
- `Resume Model`
- `Implementation Strategy`

Supporting evidence inputs used for implementation targeting, but not as canonical requirement sources:

- `docs/v0.6.0/phase0-implementation-map.md`
- `docs/v0.6.0/ops-tool-contract-alignment-plan.md`

---

## 1. Canonical state-machine model

## 1.1 Status versus continuation
The plan defines a strict distinction between:

- **status**
  - lifecycle classification
- **next_action**
  - canonical continuation dispatch

Status explains what lifecycle state the transaction is in.
`next_action` tells the system what should happen next.

## 1.2 Continuation precedence
When a valid canonical `next_action` is present, implementation must prefer it over:

- status-derived heuristics
- phase-style metadata
- step-style metadata
- reconstructed continuation guesses

This is one of the central continuation rules of `0.6.0`.

## 1.3 Explanatory versus canonical text
Status-specific “typical next action” language is explanatory guidance only.

It does **not** override:
- a valid stored `next_action`
- the canonical continuation contract
- explicit checkpoint ordering rules

---

## 2. Canonical status set

The canonical transaction status model is intentionally small and consists of exactly:

- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

This set must not be expanded by downstream implementation or documentation for canonical runtime semantics.

The no-active baseline representation may use:
- `status: null`

But `null` in that no-active baseline is **not** an additional active-transaction status.

---

## 3. Meaning of each canonical status

## 3.1 `in-progress`
Meaning:
- transaction work has started
- implementation work or repair work is ongoing
- the transaction is non-terminal

Typical next action:
- `tx.verify.start`

Continuation meaning:
- the transaction has not yet completed verification for the current state
- further work or repair may still occur before verification begins

## 3.2 `checking`
Meaning:
- the transaction is being evaluated against verification or acceptance expectations
- the transaction is non-terminal

Typical next action:
- continue verification flow
- or resume required checking work

Continuation meaning:
- the transaction is in an evaluation-oriented stage
- the exact continuation still depends on canonical `next_action`

## 3.3 `verified`
Meaning:
- verification has succeeded for the current transaction state
- the transaction is non-terminal

Typical next action:
- commit if repository changes exist
- otherwise proceed directly to explicit terminal completion

Important consequence:
- `verified` does not imply terminal success
- `verified` does not imply that a commit is always required

Special case:
- if there are no repository changes to commit, `verified -> done` is canonical
- in that case `committed` is not required as an intermediate status

## 3.4 `committed`
Meaning:
- repository commit completed successfully
- lifecycle is still non-terminal

Typical next action:
- `tx.end.done`

Important consequence:
- commit completion is not terminal success
- explicit terminal completion still must occur after commit

## 3.5 `done`
Meaning:
- terminal successful completion

Typical next action:
- none

Important consequence:
- `done` is the only successful terminal outcome in the canonical model

## 3.6 `blocked`
Meaning:
- terminal blocked completion

Typical next action:
- none

Important consequence:
- `blocked` is terminal, but not successful terminal completion

---

## 4. High-level transition model

## 4.1 Expected high-level flow
The expected high-level lifecycle flow is:

1. `in-progress`
2. `checking`
3. `verified`
4. `committed`
5. `done`

This is a high-level model, not permission to ignore `next_action`.

## 4.2 Repair-loop allowance
The plan allows repair loops.

This means execution may move back into non-terminal work before returning to verification.

Implications:
- non-terminal work may recur
- checking and verification are not guaranteed to be strictly one-pass
- repeated continuation of interrupted non-terminal states must not corrupt lifecycle meaning

## 4.3 Blocked path
A blocked terminal path ends as:

- `blocked`

No further active continuation exists after terminal blocked completion.

## 4.4 Post-terminal behavior
After terminal completion:
- the transaction is no longer active
- completed work must not remain exposed as resumable active work
- no-active materialization must become structurally explicit

---

## 5. Continuation rules

## 5.1 Primary continuation rule
The primary continuation rule is:

- continue using canonical `next_action`

This is the first-class machine-readable continuation contract.

## 5.2 Resume entrypoint
Resume should follow this logic:

1. initialize workspace
2. load canonical transaction state
3. validate materialized state
4. if state is missing or incomplete, rebuild from event log
5. if `active_tx` is `null`, no active transaction exists
6. otherwise resume that exact active transaction
7. continue using canonical `next_action`

## 5.3 Resume invariants relevant to state-machine behavior
Resume must:
- never mint a new `tx_id`
- reuse the exact existing active `tx_id`
- preserve exact active transaction identity
- preserve the distinction between non-terminal and terminal states
- preserve explicit end-of-transaction handling
- avoid duplicate logical completion when work was already committed or ended

## 5.4 Disallowed continuation behavior
Resume and continuation must not depend on:
- status-first heuristics when valid `next_action` exists
- string-shape assumptions
- sentinel transaction identifiers
- timestamp-first selection
- planning-document status as runtime truth
- optional phase-style or step-style metadata

---

## 6. Canonical checkpoint event model

## 6.1 Required canonical core checkpoint events
The minimal canonical checkpoint event set is exactly:

- `tx.begin`
- `tx.verify.start`
- `tx.verify.pass`
- `tx.verify.fail`
- `tx.commit.start`
- `tx.commit.done`
- `tx.commit.fail`
- `tx.end.done`
- `tx.end.blocked`

These events define the minimal resumable checkpoints required for deterministic continuation.

## 6.2 Event meaning by group

### Begin checkpoint
- `tx.begin`
  - creates a new transaction
  - establishes the beginning of one durable execution attempt

### Verification checkpoints
- `tx.verify.start`
  - verification begins
- `tx.verify.pass`
  - verification succeeded for the current transaction state
- `tx.verify.fail`
  - verification failed for the current transaction state

### Commit checkpoints
- `tx.commit.start`
  - repository commit attempt begins
- `tx.commit.done`
  - repository commit attempt completed successfully
- `tx.commit.fail`
  - repository commit attempt failed

### Terminal checkpoints
- `tx.end.done`
  - explicit successful terminal completion
- `tx.end.blocked`
  - explicit blocked terminal completion

## 6.3 Conditional nature of commit checkpoints
Commit checkpoints are required only when an actual repository commit is attempted.

Therefore:
- they are not mandatory in every transaction
- they are mandatory only for commit-attempt paths

## 6.4 Verified-without-commit path
If verification succeeds and there are no repository changes:
- the transaction may proceed directly from `verified` to explicit terminal completion
- omitting `tx.commit.start` and `tx.commit.done` is canonical behavior

This means downstream logic must not require a commit checkpoint where no commit is needed.

## 6.5 Optional progress events
Additional progress events may exist for:
- observability
- operator guidance
- tooling convenience

But they are not required to define canonical resumable continuation.

Therefore:
- optional progress events must not be promoted into required canonical checkpoint events
- optional progress events must not displace the canonical role of the core checkpoint set

---

## 7. Requirement statements for `p1-t02`

## 7.1 `REQ-P1-STATE-MACHINE`
The canonical state-machine rules for `0.6.0` are:

1. The canonical active-transaction status set is exactly:
   - `in-progress`
   - `checking`
   - `verified`
   - `committed`
   - `done`
   - `blocked`
2. Status classifies lifecycle state.
3. `next_action` is the primary continuation dispatcher.
4. A valid canonical `next_action` must be preferred over status-derived heuristics.
5. The expected high-level non-terminal-to-terminal flow is:
   - `in-progress`
   - `checking`
   - `verified`
   - `committed`
   - `done`
6. Repair loops may return execution to resumable non-terminal work before verification succeeds again.
7. `done` is terminal successful completion.
8. `blocked` is terminal blocked completion.
9. Terminal completion removes the transaction from active resumability.
10. The no-active baseline representation is structurally explicit and does not add a new active status.

## 7.2 `REQ-P1-CHECKPOINTS`
The canonical checkpoint rules for `0.6.0` are:

1. The canonical core checkpoint event set is exactly:
   - `tx.begin`
   - `tx.verify.start`
   - `tx.verify.pass`
   - `tx.verify.fail`
   - `tx.commit.start`
   - `tx.commit.done`
   - `tx.commit.fail`
   - `tx.end.done`
   - `tx.end.blocked`
2. These events define the minimal resumable checkpoints required for deterministic continuation.
3. Commit checkpoint events are required only when a repository commit is actually attempted.
4. If verification succeeds and there are no repository changes, direct `verified -> done` is canonical.
5. Optional progress events may exist, but they must not be elevated into required canonical continuation checkpoints.
6. Explicit terminal completion remains separate from commit completion.
7. Canonical continuation must preserve begin, verify, commit, and end ordering semantics.

---

## 8. Traceability matrix

| Requirement ID | Requirement summary | Canonical source sections | Implementation review targets |
| --- | --- | --- | --- |
| `REQ-P1-STATE-MACHINE` | Define the canonical status set, lifecycle meanings, and `next_action`-first continuation behavior | `Canonical State Machine`; `Status set`; `Meaning of each status`; `State-machine constraints`; `Resume Model`; `Implementation Strategy` | Continuation dispatch logic, resume logic, workflow guidance responses, active-state classification, terminal handling |
| `REQ-P1-CHECKPOINTS` | Define the minimal canonical checkpoint event set and the distinction between required checkpoints and optional progress events | `Canonical Checkpoints and Events`; `Resume Model`; `Implementation Strategy` | Event emission logic, lifecycle helper sequencing, verify/commit/end handling, optional progress-event handling |

---

## 9. Implementation-facing review checklist

## 9.1 State-machine checklist
A later implementation satisfies `p1-t02` state-machine rules only if all of the following are true:

- the active-transaction status set matches `plan.md` exactly
- no additional canonical statuses are introduced
- valid `next_action` is preferred over status-derived heuristics
- explanatory “typical next action” guidance is not treated as overriding continuation truth
- terminal states are not resumed as active work
- post-terminal materialization does not leave ambiguity about active resumability
- no-active baseline remains structurally explicit rather than sentinel-based

## 9.2 Checkpoint checklist
A later implementation satisfies `p1-t02` checkpoint rules only if all of the following are true:

- the canonical core checkpoint set matches `plan.md` exactly
- begin, verify, commit, and end checkpoints preserve strict ordering meaning
- commit checkpoints are emitted only when a commit is attempted
- verified-without-commit paths may proceed directly to explicit terminal completion
- optional progress events are not treated as required canonical continuation checkpoints
- explicit end-of-transaction handling remains distinct from commit completion

## 9.3 `ops_*` helper continuation checklist
When downstream implementation updates `ops_*` helper contracts, the following must remain true:

- helper behavior does not let status override a valid `next_action`
- helper behavior does not invent extra canonical states
- helper behavior does not invent extra canonical checkpoint events
- helper convenience does not hide or collapse the semantic distinction between checkpoint classes
- begin/bootstrap convenience, if retained, does not erase the explicit ordering meaning of canonical checkpoints

This checklist is derived support for downstream implementation work. It does not add new canonical requirements beyond the plan.

---

## 10. Gap checklist template for current-code review

This section defines how downstream tickets should compare runtime code against the plan without mixing observation and requirement.

For each relevant runtime module, findings should be labeled as one of:
- **plan-aligned**
- **gap against plan**
- **not in scope for `p1-t02`**

### Required review questions
1. Does any continuation path let status override a valid canonical `next_action`?
2. Does any implementation introduce additional canonical statuses beyond the plan-defined set?
3. Does any implementation treat optional progress events as required canonical continuation checkpoints?
4. Does any implementation require commit checkpoints even when no repository commit is attempted?
5. Does any implementation collapse commit completion into terminal success?
6. Does any implementation resume terminal transactions as active work?
7. Does any helper path blur the distinction between explanatory typical-next-action text and canonical continuation truth?
8. Does any lifecycle helper hide canonical checkpoint ordering in a way that changes semantic meaning rather than merely wrapping it?

This checklist defines the required review lens. It does not itself answer the questions.

---

## 11. Input consistency check for `p1-t02`

This section verifies that the current `inputs` field for `p1-t02` is complete and non-contradictory relative to the ticket’s purpose.

## 11.1 `docs/v0.6.0/plan.md`
Required and correct.
- It is the canonical source of requirements.
- All normative state-machine and checkpoint statements in this artifact derive from it.

## 11.2 `docs/v0.6.0/phase0-implementation-map.md`
Required and correct.
- It is not a canonical requirement source.
- It is an implementation-targeting evidence artifact.
- It helps connect continuation and checkpoint semantics to runtime modules such as `ops_tools.py`, `commit_manager.py`, `state_rebuilder.py`, and `workflow_response.py`.

## 11.3 `docs/v0.6.0/ops-tool-contract-alignment-plan.md`
Required and correct.
- It is not a canonical requirement source.
- It is a downstream implementation-planning artifact focused on helper contract alignment.
- It is relevant because helper contract updates must preserve `next_action` precedence, checkpoint ordering, and the distinction between required checkpoints and optional progress events.

## 11.4 No contradiction check
There is no contradiction among the current inputs because:
- only `plan.md` is treated as canonical
- the other two inputs are explicitly treated as derived evidence/planning artifacts
- no statement in this artifact relies on them to override plan-defined state-machine or checkpoint semantics

## 11.5 No missing-input conclusion
For the current scope of `p1-t02`, no additional mandatory input is required.

Reason:
- `p1-t02` is a state-machine-and-checkpoint contract ticket
- identity boundary details belong primarily to `p1-t01`
- persistence and issuance details belong to `p1-t03`
- the listed inputs are sufficient to produce the required specification, traceability, and review lens without introducing non-plan requirements

---

## 12. Explicit non-goals
This artifact must not be used to justify any of the following:

- introducing new transaction statuses beyond those defined in `plan.md`
- redefining transaction identity semantics
- redefining persistence schema details
- inventing extra canonical checkpoint events outside the plan
- allowing status-derived heuristics to override valid canonical `next_action`
- treating planning artifacts under `docs/` as canonical runtime truth

---

## 13. Acceptance mapping for `p1-t02`

### Acceptance criterion 1
The canonical status set matches `plan.md` exactly.

Satisfied by:
- `Canonical status set`
- `Meaning of each canonical status`
- `REQ-P1-STATE-MACHINE`

### Acceptance criterion 2
The continuation rules explicitly preserve `next_action` precedence over status-derived heuristics when `next_action` is valid.

Satisfied by:
- `Continuation precedence`
- `Continuation rules`
- `REQ-P1-STATE-MACHINE`
- `Implementation-facing review checklist`

### Acceptance criterion 3
The checkpoint-event contract does not require commit events when no repository commit is attempted.

Satisfied by:
- `Conditional nature of commit checkpoints`
- `Verified-without-commit path`
- `REQ-P1-CHECKPOINTS`

### Acceptance criterion 4
The artifact remains strictly derived from `plan.md` and does not invent new canonical semantics.

Satisfied by:
- the authority rule in `Status`
- the source discipline in `Canonical source sections used`
- the explicit non-canonical treatment of supporting inputs
- `Explicit non-goals`

---

## 14. Summary
`p1-t02` defines the canonical state machine and continuation rules for `0.6.0`.

Its core consequences are:

- the canonical active-transaction status set is intentionally small and fixed
- `next_action` is the primary continuation dispatcher
- valid `next_action` must not be overridden by status-derived heuristics
- the canonical checkpoint set is minimal and explicit
- commit checkpoints are conditional on an actual commit attempt
- explicit terminal completion remains distinct from commit completion
- optional progress events may exist, but they must not become required canonical continuation checkpoints

These are the plan-derived continuation and checkpoint rules that downstream implementation tickets must preserve.