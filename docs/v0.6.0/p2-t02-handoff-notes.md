# p2-t02 Handoff Notes

## Purpose
This note captures the intentionally deferred follow-up work discovered while implementing `p2-t02`.

It is a derived planning and handoff artifact.
It does not add canonical requirements beyond:

- `docs/v0.6.0/plan.md`
- `docs/v0.6.0/p2-t02.json`
- `docs/v0.6.0/p2-t03.json`
- `docs/v0.6.0/p2-t04.json`

Its purpose is to make later phase-2 work more explicit and easier to resume without reopening `p2-t02` scope unnecessarily.

---

## Source ticket
- `ticket_id`: `p2-t02`
- `title`: `Remove sentinel active-transaction semantics from normal flow`

## Handoff targets
Primary follow-up targets:
- `p2-t03` `Simplify resume logic to continue the exact active transaction`
- `p2-t04` `Bound session context and define historical compatibility behavior`

---

## What p2-t02 completed
`p2-t02` addressed the core no-sentinel active-transaction requirement in the main normal-flow runtime areas.

Implemented directions:
- removed normal-flow fake active-transaction identity handling based on values such as:
  - `tx_id = 0`
  - `ticket_id = "none"`
- preserved structural no-active materialization based on:
  - `active_tx: null`
  - `status: null`
  - `next_action: tx.begin`
  - `semantic_summary: null`
  - `verify_state: null`
  - `commit_state: null`
- reduced sentinel-based replay behavior in rebuild logic
- stopped normal rebuild handling from collapsing malformed or missing transaction identity into pseudo-identity defaults

Primary runtime files changed during `p2-t02`:
- `src/agentops_mcp_server/state_store.py`
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/state_rebuilder.py`

---

## Why this handoff exists
During `p2-t02`, some adjacent issues were identified that are real follow-up concerns, but they were not required to satisfy the core no-sentinel active-transaction objective.

Those issues should not reopen `p2-t02` unless they are shown to reintroduce fake active transaction identity into normal canonical behavior.

Instead, they should be treated as planned downstream cleanup under `p2-t03` and `p2-t04`.

---

## Deferred concern 1: helper step placeholder cleanup in `commit_manager.py`
### Observation
`commit_manager.py` still contains helper bootstrap behavior that uses `"none"` as step placeholder data, for example around:
- `current_step = "none"`
- `step_id = "none"`

### Why this was deferred
This remaining `"none"` usage appears in step metadata rather than in canonical active transaction identity fields such as:
- `tx_id`
- `ticket_id`

Because `p2-t02` is specifically about sentinel active-transaction semantics, this placeholder vocabulary was not treated as the blocking core issue for the ticket.

### Why it still matters
Even if it is not fake transaction identity, it still creates representational inconsistency with the direction established by:
- structural no-active state
- reduced sentinel handling in normal runtime flow
- exact-resume and helper-contract cleanup goals in later phase-2 work

### Recommended follow-up ticket
Primary:
- `p2-t03`

Secondary:
- `p2-t04`

### Suggested downstream handling
Later work should review whether helper bootstrap paths should:
- replace `"none"` step placeholders with explicit neutral step values
- preserve exact continuation semantics without placeholder-driven ambiguity
- keep helper lifecycle behavior aligned with `next_action`-first continuation rules

---

## Deferred concern 2: helper contract consistency across resume-related runtime surfaces
### Observation
After the `p2-t02` changes, the core no-sentinel identity behavior improved, but helper-facing runtime surfaces still need consistency review across files such as:
- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/repo_tools.py`
- `src/agentops_mcp_server/workflow_response.py`

### Why this was deferred
`p2-t02` focused on removing sentinel active-transaction semantics from normal flow, not on fully harmonizing all helper contract and continuation response surfaces.

### Why it still matters
Later phase-2 tickets explicitly require:
- exact-active-transaction continuation
- `next_action`-first continuation
- bounded helper-context recovery
- non-heuristic canonical continuation

Those outcomes depend on the surrounding helper contract surfaces being consistent, even where fake active identity has already been removed.

### Recommended follow-up tickets
Primary:
- `p2-t03`

Secondary:
- `p2-t04`

### Suggested downstream handling
Review for:
- `active_tx` representation consistency in no-active cases
- `active_tx_id` and `active_ticket_id` consistency in guidance responses
- avoidance of heuristic active replacement
- avoidance of status-over-`next_action` continuation behavior
- helper bootstrap behavior that may obscure exact resume semantics

---

## Deferred concern 3: bounded historical compatibility remains a separate concern
### Observation
`p2-t02` intentionally did not perform:
- historical in-place rewrite
- broad compatibility redesign
- initialization-artifact cleanup outside the core normal-flow runtime changes

Historical or initialization artifacts may still contain sentinel-shaped older material.

### Why this was deferred
`p2-t02.json` explicitly marks these broader compatibility changes as out of scope.

### Why it still matters
The plan requires:
- bounded compatibility
- explicit failure for malformed or ambiguous persistence
- no weakening of strict new canonical semantics

So later work should ensure historical handling remains readable only where deterministically safe, without normalizing bad persistence into healthy canonical state.

### Recommended follow-up ticket
Primary:
- `p2-t04`

### Suggested downstream handling
Review:
- historical sentinel-bearing logs
- helper recovery paths that may still assume older conventions
- compatibility boundaries between readable historical data and invalid malformed persistence
- any initialization or support artifacts that still imply fake active identity in ways that could confuse later maintenance work

---

## Ticket-to-concern map

### `p2-t03`
Best fit for:
- exact resume behavior refinement after `p2-t02`
- helper bootstrap consistency related to resume semantics
- cleanup of step placeholder usage where it interferes with exact continuation understanding
- response and helper alignment for `next_action`-first continuation

Suggested files to review:
- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/repo_tools.py`
- `src/agentops_mcp_server/workflow_response.py`
- `src/agentops_mcp_server/ops_tools.py`

### `p2-t04`
Best fit for:
- bounded compatibility behavior
- helper-context recovery boundaries
- session-sensitive recovery logic
- historical sentinel-shaped artifacts that should remain bounded and non-authoritative

Suggested files and artifacts to review:
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/state_rebuilder.py`
- initialization / support artifacts under the project root that may preserve older conventions

---

## Recommended updates to downstream ticket inputs

### Recommended input addition for `p2-t03`
Add this file as an implementation input:
- `docs/v0.6.0/p2-t02-handoff-notes.md`

Suggested rationale:
- it records deferred helper and resume-consistency follow-up from `p2-t02`

### Recommended input addition for `p2-t04`
Add this file as an implementation input:
- `docs/v0.6.0/p2-t02-handoff-notes.md`

Suggested rationale:
- it records deferred compatibility-boundary and helper-context follow-up from `p2-t02`

---

## Non-goals of this handoff
This note should not be interpreted as:
- reopening `p2-t02` identity-removal scope
- adding new canonical requirements
- asserting that all remaining `"none"` strings are protocol bugs
- requiring broad placeholder-vocabulary cleanup outside the later ticket scopes

---

## Short handoff summary
`p2-t02` completed the core removal of sentinel active-transaction identity handling from normal runtime flow.

Deferred follow-up remains in two main areas:
1. helper / resume / response consistency, especially around placeholder-driven helper behavior
2. bounded compatibility and helper-context recovery for historical or adjacent surfaces

Those follow-ups should be handled by:
- `p2-t03` for exact-resume and helper-contract continuation alignment
- `p2-t04` for bounded compatibility and helper-context recovery alignment