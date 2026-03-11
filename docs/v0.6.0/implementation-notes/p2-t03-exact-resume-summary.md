# p2-t03 Exact-Resume Implementation Summary

## Status
- **Artifact type**: implementation traceability note
- **Primary ticket**: `docs/v0.6.0/p2-t03.json`
- **Canonical source**: `docs/v0.6.0/plan.md`
- **Related implementation-planning note**: `docs/v0.6.0/ops-tool-contract-alignment-plan.md`
- **Authority rule**: this document is derived implementation evidence and does not add canonical requirements beyond `plan.md`

---

## Purpose
This note records the implementation-side traceability for `p2-t03`:

- exact active transaction continuation
- healthy materialized state as the primary resume entrypoint
- rebuild-only fallback behavior
- explicit failure on malformed or ambiguous canonical persistence
- alignment of resume-related helper and guidance surfaces

It exists to support strict review of whether the runtime behavior now matches the `0.6.0` exact-resume requirements.

---

## Canonical requirement summary
`p2-t03` implements the `plan.md` rule that resume must:

1. continue the exact active transaction
2. prefer healthy materialized state
3. use top-level `next_action` as the primary continuation guide
4. use rebuild only when materialized state is missing, incomplete, or inconsistent
5. fail explicitly when exact deterministic continuation is not safely possible
6. avoid heuristic active-transaction replacement
7. avoid resuming post-terminal work as active work

---

## Runtime surfaces reviewed
The following runtime files were reviewed and updated or re-checked as part of `p2-t03` scope:

- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/repo_tools.py`
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/workflow_response.py`
- `src/agentops_mcp_server/state_rebuilder.py`

---

## Direct materialized-state resume rules
The exact-resume implementation now treats materialized state as the primary resume anchor when it is healthy enough for direct continuation.

### Healthy direct-resume conditions
For non-terminal active resume, direct materialized-state continuation requires:

- `active_tx` is a dictionary
- top-level `status` exists and is non-empty
- top-level `status` is not terminal
- top-level `next_action` exists and is non-empty
- canonical identity fields remain structurally valid
- required top-level verification / commit / semantic summary fields remain structurally valid on the relevant runtime surface

### No-active baseline conditions
The structural no-active baseline remains valid when:

- `active_tx` is `null`
- `status` is `null`
- `next_action` is `tx.begin`

This remains a valid no-active representation rather than a resumable active transaction.

---

## Rebuild fallback rules
Rebuild is used only as fallback behavior when direct materialized-state resume is not safe.

### Rebuild-eligible cases
Fallback rebuild is used when materialized state is:

- missing
- incomplete
- inconsistent for exact-resume purposes

### Rebuild success conditions
A rebuild result is accepted for exact resume only when:

- rebuild completes successfully
- rebuild integrity is not drift-blocked
- rebuilt state contains a structurally valid exact active transaction snapshot
- rebuilt top-level `next_action` is valid for continuation
- rebuilt state is not terminal when active continuation is required

---

## Explicit failure rules
`p2-t03` requires explicit failure rather than silent fallback when exact deterministic continuation is not safely possible.

### Explicit failure cases
The implementation now treats the following as explicit failure conditions on exact-resume paths:

- ambiguous canonical persistence signaled by rebuild integrity drift
- malformed canonical persistence that cannot be resumed safely
- rebuilt canonical state that is still incomplete for exact resume
- active transaction state missing canonical top-level `next_action`
- terminal transaction encountered on a resume-as-active path

### Important non-goal
This ticket does **not** redesign broad bounded historical compatibility policy.
That remains primarily within `p2-t04`.
`p2-t03` only enforces the exact-resume rule that malformed or ambiguous persistence must not be silently normalized into healthy active continuation.

---

## next_action-first continuation traceability
The runtime surfaces were aligned to preserve top-level `next_action` as the primary continuation guide.

### Observed implementation direction
- active resume context loaders require a valid top-level `next_action`
- verify-related flows reject missing canonical `next_action`
- workflow guidance derives continuation primarily from top-level state
- rebuilt `next_action` remains fallback-only and does not replace healthy materialized continuation

### Protected behavior
The implementation is intended to avoid:

- status-only continuation when canonical `next_action` is missing
- phase-style metadata replacing canonical top-level `next_action`
- reconstructed guesses overriding healthy materialized continuation
- helper-driven status-over-`next_action` resume behavior

---

## Exact-identity preservation traceability
The runtime surfaces were reviewed to preserve exact active transaction identity.

### Protected behavior
The implementation is intended to ensure that resume:

- reuses the exact existing `tx_id`
- does not mint a replacement `tx_id` for existing active work
- does not replace the active transaction with a heuristic candidate
- does not promote `ticket_id`, `task_id`, `session_id`, or other helper context into canonical runtime identity

### Boundary note
- `ticket_id` remains a client-managed work label
- `task_id` remains helper-facing compatibility context
- `session_id` remains secondary continuity / observability context
- `tx_id` remains the canonical runtime execution identity

---

## Resume-related surface alignment summary

### `commit_manager.py`
Reviewed for:

- materialized-state-first resume loading
- fallback rebuild behavior
- exact `tx_id` reuse
- explicit failure on malformed / ambiguous canonical persistence
- no post-terminal active continuation
- no heuristic active-transaction replacement in helper bootstrap paths

### `repo_tools.py`
Reviewed for:

- verify-path resume loading
- exact active transaction reuse
- `next_action`-required verification behavior
- explicit failure on malformed / ambiguous canonical persistence
- no post-terminal verification resume

### `ops_tools.py`
Reviewed for:

- exact active transaction requirement on helper paths
- helper-facing resume protection using canonical `tx_id`
- explicit failure on malformed / ambiguous canonical persistence
- helper context remaining secondary rather than canonical identity
- response and guidance alignment with exact-resume rules

### `workflow_response.py`
Reviewed for:

- guidance fields derived from canonical transaction state
- `next_action`-first guidance behavior
- exact active transaction visibility through `active_tx_id` / `active_ticket_id`
- prevention of response-layer status-only continuation assumptions

### `state_rebuilder.py`
Reviewed for fallback-only relevance:

- rebuild integrity validation
- active transaction reconstruction rules
- derived `next_action` behavior remaining subordinate to healthy materialized state
- no fallback normalization of malformed active identity into healthy exact resume

---

## Acceptance-criteria traceability summary

### Satisfied by implementation direction
The current implementation direction for `p2-t03` is intended to satisfy:

- resume never mints a new `tx_id` for an existing active transaction
- resume never replaces the active transaction with a heuristic candidate when exact active state is available
- healthy materialized state is the primary resume entrypoint
- rebuild is used only as fallback when materialized state is missing, incomplete, or inconsistent
- malformed or ambiguous canonical persistence causes explicit failure rather than silent fallback
- valid canonical `next_action` is preferred over status-derived heuristics and reconstructed guesses
- post-terminal work is not resumed as active work
- helper context is not promoted into canonical runtime transaction identity

### Alignment note
Resume-related workflow guidance was also reviewed for consistency across:

- helper paths
- verify paths
- commit-adjacent paths
- response surfaces

---

## Scope boundary reminder
This note should **not** be interpreted as claiming that `p2-t03` implements:

- issued `tx_id` allocation semantics beyond `p2-t01`
- full bounded historical compatibility redesign beyond `p2-t04`
- new canonical protocol fields not already present in `plan.md`

---

## Short implementation summary
`p2-t03` hardens the runtime around one rule:

> if an exact active transaction already exists, resume that exact transaction from healthy materialized state using top-level `next_action`; use rebuild only as bounded fallback; and fail explicitly when canonical persistence is malformed or ambiguous.

This is the core exact-resume behavior required by `docs/v0.6.0/plan.md`.

---

## Strict-review remediation proposal

The following remediation items capture the remaining gaps identified during strict review of `p2-t03`.
They are derived implementation follow-ups and do not add new canonical requirements beyond `plan.md`.

### High priority

1. **Tighten no-active baseline validation in `commit_manager.py`.**
   - Update `_is_valid_materialized_tx_state()` so the no-active baseline only validates when:
     - `active_tx` is `null`
     - `status` is `null`
     - `next_action` is exactly `tx.begin`
     - `verify_state` is `null`
     - `commit_state` is `null`
     - `semantic_summary` is `null`
   - Do not treat arbitrary non-empty `next_action` values as valid no-active canonical state.

2. **Tighten no-active baseline validation in `repo_tools.py`.**
   - Update `_is_valid_materialized_tx_state()` to use the same strict no-active baseline contract as above.
   - Keep no-active materialized validation consistent across resume-related runtime surfaces.

3. **Return canonical no-active baseline from `ops_tools.py` when materialized state is missing.**
   - In `_load_tx_state()`, replace the empty-dictionary fallback for missing materialized state with the canonical no-active baseline structure:
     - `active_tx: null`
     - `status: null`
     - `next_action: tx.begin`
     - `verify_state: null`
     - `commit_state: null`
     - `semantic_summary: null`
     - `integrity: {}`
   - Avoid using `{}` as a substitute for canonical no-active state.

### Medium priority

4. **Re-evaluate `commit_manager._ensure_tx_begin()` rebuild-based repair behavior.**
   - Review the branch that writes rebuilt active transaction fields back into materialized state during helper bootstrap.
   - Either:
     - remove the repair path if it is not required for exact-resume correctness, or
     - constrain and document it so it cannot act like heuristic active-transaction replacement or silent normalization of malformed canonical persistence.
   - Exact-resume continuation should remain anchored in healthy materialized state first, with bounded rebuild fallback and explicit failure when deterministic continuation is not safely possible.

### Low priority

5. **Deduplicate baseline-validation logic across resume-related runtime surfaces.**
   - Extract the canonical no-active and active-state validation contract into shared logic used by:
     - `commit_manager.py`
     - `repo_tools.py`
     - `ops_tools.py`
   - This reduces drift risk and helps keep exact-resume semantics aligned across helper, verify, and response-adjacent flows.