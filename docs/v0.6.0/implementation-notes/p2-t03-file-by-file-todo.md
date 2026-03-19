# p2-t03 File-by-File Implementation TODO

## Status
- **Artifact type**: implementation task breakdown
- **Primary ticket**: `docs/v0.6.0/p2-t03.json`
- **Derived from**:
  - `docs/v0.6.0/implementation-notes/p2-t03-exact-resume-summary.md`
  - `docs/v0.6.0/ops-tool-contract-alignment-plan.md`
  - `docs/v0.6.0/plan.md`
- **Authority rule**: this document is a derived implementation-planning artifact and does not add canonical requirements beyond `plan.md`

---

## Purpose
This note converts the `p2-t03` strict-review remediation plan into a file-by-file implementation checklist.

It is intended to help implementation proceed in a bounded order while preserving the `p2-t03` scope:

- exact active transaction continuation
- healthy materialized state as the primary resume anchor
- rebuild-only fallback behavior
- explicit failure on malformed or ambiguous canonical persistence
- top-level `next_action` as the canonical continuation guide

---

## Scope boundary
This breakdown must stay within `p2-t03` boundaries.

### In scope
- strict no-active baseline handling
- exact-resume validation consistency
- helper bootstrap hardening
- continuation-guidance consistency
- fallback-only rebuild safety review

### Out of scope
- changing issued `tx_id` semantics from `p2-t01`
- broad historical compatibility redesign from `p2-t04`
- adding new canonical protocol fields
- rewriting historical logs or snapshots in place
- redefining helper metadata as canonical identity

---

## Recommended implementation order

1. `src/agentops_mcp_server/workflow_response.py`
2. `src/agentops_mcp_server/commit_manager.py`
3. `src/agentops_mcp_server/repo_tools.py`
4. `src/agentops_mcp_server/ops_tools.py`
5. `src/agentops_mcp_server/state_rebuilder.py`
6. verification and documentation sync

This order keeps the shared exact-resume contract stable before updating runtime callers.

---

## 1. `src/agentops_mcp_server/workflow_response.py`

### Role in `p2-t03`
This file should be the primary home for shared exact-resume validation behavior and shared malformed/incomplete/integrity failure handling.

### Implementation goals
- define one strict exact-resume validation contract
- keep no-active baseline handling canonical and explicit
- keep malformed versus incomplete versus ambiguous failure cases machine-distinguishable

### TODO
- [ ] Review the existing exact-resume validation entrypoints and identify the single shared validator path.
- [ ] Ensure the strict canonical no-active baseline validates only when all of the following are true:
  - [ ] `active_tx` is `None`
  - [ ] `status` is `None`
  - [ ] `next_action` is exactly `tx.begin`
  - [ ] `verify_state` is `None`
  - [ ] `commit_state` is `None`
  - [ ] `semantic_summary` is `None`
- [ ] Ensure an active exact-resume state validates only when all of the following are true:
  - [ ] `active_tx` is a dictionary
  - [ ] `active_tx.tx_id` is an integer and not a boolean
  - [ ] `active_tx.ticket_id` is a non-empty string
  - [ ] top-level `status` is a non-empty string
  - [ ] top-level `status` is not terminal
  - [ ] top-level `next_action` is a non-empty string
- [ ] Reject malformed pseudo-baselines such as:
  - [ ] `active_tx is None` with non-null `status`
  - [ ] `active_tx is None` with non-`tx.begin` `next_action`
  - [ ] `active_tx is None` with non-null `verify_state`
  - [ ] `active_tx is None` with non-null `commit_state`
  - [ ] `active_tx is None` with non-null `semantic_summary`
- [ ] Confirm the exact-resume validator does not silently accept partially populated active state.
- [ ] Review `requests_resume_state_rebuild()` and ensure it stays aligned with the same strict contract.
- [ ] Confirm canonical no-active baseline does not incorrectly trigger rebuild.
- [ ] Confirm malformed materialized state does trigger rebuild or explicit failure as intended.
- [ ] Keep failure payload construction distinct for:
  - [ ] integrity drift / ambiguity
  - [ ] rebuilt-but-incomplete state
  - [ ] malformed materialized state
  - [ ] malformed rebuild result
- [ ] Ensure failure messages consistently refer to restoring exact active continuation using top-level `next_action`.

### Expected outcome
- one shared validation contract governs exact-resume state acceptance
- no-active baseline handling is strict and canonical
- callers no longer need local permissive interpretations of resumable state

---

## 2. `src/agentops_mcp_server/commit_manager.py`

### Role in `p2-t03`
This file controls helper bootstrap and commit-adjacent transaction progression, so it must not repair malformed persistence in ways that blur exact-resume guarantees.

### Implementation goals
- use the shared strict exact-resume contract
- prevent helper bootstrap from silently normalizing malformed state
- preserve exact transaction identity and top-level `next_action` guidance

### TODO

#### Shared validation alignment
- [ ] Update `_is_valid_materialized_tx_state()` to rely on the strict shared validator only.
- [ ] Confirm `commit_manager.py` no longer accepts permissive no-active materialized state shapes.
- [ ] Confirm malformed no-active state cannot be treated as healthy baseline state.

#### Active context loading
- [ ] Review `_load_tx_context()` and keep the following requirements explicit:
  - [ ] `active_tx` must be a dict
  - [ ] top-level `status` must be present and non-terminal
  - [ ] `active_tx.tx_id` must be an integer
  - [ ] `active_tx.ticket_id` must be a non-empty string
  - [ ] top-level `next_action` must be present and non-empty
- [ ] Confirm `session_id` remains fallback continuity metadata only, not canonical identity.

#### Helper bootstrap hardening
- [ ] Re-evaluate `_ensure_tx_begin()` behavior when:
  - [ ] materialized state suggests an active transaction
  - [ ] event log is empty or inconsistent
  - [ ] rebuild cannot safely confirm the same exact active transaction
- [ ] Review whether helper bootstrap should emit `tx.begin` in any case where exact deterministic continuation is unsafe.
- [ ] If bootstrap repair behavior remains, constrain it so that it is only used when it cannot act like heuristic replacement.
- [ ] Add explicit failure behavior for:
  - [ ] malformed canonical persistence
  - [ ] incomplete rebuilt state
  - [ ] integrity drift / ambiguity
  - [ ] materialized/rebuilt mismatch that prevents exact continuation
- [ ] Confirm helper bootstrap does not silently create the appearance of a valid active transaction when canonical evidence is insufficient.

#### Event-state mutation review
- [ ] Review `_emit_tx_begin_with_context()` and confirm it does not become a repair path for malformed exact-resume state unless explicitly justified and bounded.
- [ ] Review `_emit_tx_event()` and confirm canonical continuation remains sourced from top-level state, not nested mirror fields.
- [ ] If nested `active_tx.next_action` remains, treat it as mirrored metadata only.

### Expected outcome
- helper bootstrap no longer bypasses exact-resume safety rules
- malformed or ambiguous persistence fails explicitly instead of being normalized
- commit-adjacent helpers preserve exact active transaction identity

---

## 3. `src/agentops_mcp_server/repo_tools.py`

### Role in `p2-t03`
This file controls verify-path exact-resume behavior and must stay aligned with the same strict rules used by helper and commit-adjacent flows.

### Implementation goals
- enforce the shared exact-resume contract on verify paths
- keep top-level `next_action` mandatory for active verify continuation
- avoid verify-path permissiveness that diverges from helper behavior

### TODO

#### Shared validation alignment
- [ ] Update `_is_valid_materialized_tx_state()` to rely on the strict shared validator only.
- [ ] Confirm strict no-active baseline handling matches `commit_manager.py`.
- [ ] Confirm malformed no-active state is not accepted as canonical baseline.

#### Active context loading
- [ ] Review `_load_tx_context()` and keep the same exact-active requirements used elsewhere:
  - [ ] active transaction dict required
  - [ ] top-level non-terminal `status` required
  - [ ] top-level non-empty `next_action` required
  - [ ] exact `tx_id` required
  - [ ] non-empty `ticket_id` required
- [ ] Confirm no verify-path logic selects or reconstructs an active transaction heuristically when exact active state is already available.

#### Verify flow safety
- [ ] Review `repo_verify()` behavior when no exact active transaction exists.
- [ ] Confirm no-active baseline behavior remains distinct from active-resume behavior.
- [ ] Confirm malformed active state with missing canonical `next_action` still fails explicitly.
- [ ] Confirm terminal transactions cannot be resumed through verify paths.
- [ ] Review `_emit_tx_event()` and ensure event updates do not reintroduce status-over-`next_action` continuation logic.

### Expected outcome
- verify-path continuation rules match helper and commit-adjacent exact-resume rules
- no separate permissive verify-only interpretation remains
- canonical top-level `next_action` stays required for active verify continuation

---

## 4. `src/agentops_mcp_server/ops_tools.py`

### Role in `p2-t03`
This file exposes helper-facing behavior and operator-facing summaries, so it must not drift into non-canonical continuation guidance.

### Implementation goals
- use canonical no-active baseline instead of empty placeholders
- keep helper enforcement aligned with exact active transaction rules
- standardize guidance on top-level `tx_state.next_action`

### TODO

#### Canonical baseline handling
- [ ] Review `_load_tx_state()` and ensure canonical no-active baseline is used instead of empty-dictionary substitutes.
- [ ] Confirm helper paths receive the same canonical no-active shape used elsewhere.
- [ ] Confirm response assembly does not depend on `{}` as a stand-in for no-active canonical state.

#### Active-transaction enforcement
- [ ] Review `_require_active_tx()` against the shared exact-resume contract.
- [ ] Confirm it still rejects:
  - [ ] missing canonical active transaction
  - [ ] incomplete top-level `status`
  - [ ] terminal transaction continuation
  - [ ] missing canonical top-level `next_action`
  - [ ] mismatched requested transaction identity
- [ ] Confirm helper-facing failure responses continue to point callers back to exact active continuation rather than ticket switching.

#### Guidance consistency audit
- [ ] Audit helper and summary surfaces for any place where continuation is derived from:
  - [ ] `active_tx.next_action`
  - [ ] `active_tx.current_step`
  - [ ] status-only heuristics
- [ ] Keep `ops_compact_context()` aligned with top-level `tx_state.next_action`.
- [ ] Keep `ops_resume_brief()` aligned with top-level `tx_state.next_action`.
- [ ] Review `ops_task_summary()` and change continuation guidance so:
  - [ ] top-level `tx_state.next_action` is the primary continuation source
  - [ ] `current_step` is only auxiliary context, not the canonical next step
  - [ ] nested `active_tx.next_action` is not treated as the canonical guide
- [ ] Review `_active_tx_mismatch_error()` and prefer top-level continuation guidance where possible.

#### Workflow response consistency
- [ ] Review `_workflow_success_response()` and ensure it assembles no-active baseline and guidance consistently with the shared contract.
- [ ] Confirm helper-facing success responses do not quietly reintroduce permissive baseline interpretation.

### Expected outcome
- helper and summary surfaces use canonical top-level continuation guidance
- no-active baseline is represented consistently
- helper behavior remains aligned with exact-resume requirements

---

## 5. `src/agentops_mcp_server/state_rebuilder.py`

### Role in `p2-t03`
This file remains fallback-only for exact-resume purposes, but its candidate-selection and rebuilt-state behavior must not undermine exact active continuation.

### Implementation goals
- keep rebuild subordinate to healthy materialized state
- prevent heuristic rebuilt selection from masquerading as exact healthy continuation
- preserve explicit ambiguity signaling

### TODO

#### Fallback-only boundary review
- [ ] Review rebuilt-state generation and confirm it is only relied on when materialized state is missing, incomplete, or inconsistent.
- [ ] Confirm rebuild is not treated as equal priority with healthy materialized state.

#### Candidate selection and ambiguity
- [ ] Review active transaction candidate selection behavior.
- [ ] Identify whether candidate selection can produce ambiguous-but-apparently-valid rebuilt state.
- [ ] Confirm ambiguity is surfaced through integrity or rebuild-warning signals rather than silently accepted as healthy exact continuation.
- [ ] If necessary, tighten drift or ambiguity reporting so heuristic candidate selection cannot be mistaken for exact active resume.

#### Rebuilt-state contract alignment
- [ ] Confirm rebuilt no-active baseline shape matches the strict canonical baseline:
  - [ ] `active_tx: None`
  - [ ] `status: None`
  - [ ] `next_action: tx.begin`
  - [ ] `verify_state: None`
  - [ ] `commit_state: None`
  - [ ] `semantic_summary: None`
- [ ] Confirm rebuilt active state shape remains compatible with the shared exact-resume validator.
- [ ] Review rebuild-derived `next_action` logic and confirm it remains fallback-only guidance.

### Expected outcome
- rebuild remains a bounded fallback path
- ambiguous candidate selection is surfaced rather than normalized
- rebuilt states align with the same strict validation contract used elsewhere

---

## 6. Cross-file cleanup and consistency tasks

### Goal
After individual file changes, remove remaining drift between runtime surfaces.

### TODO
- [ ] Confirm `commit_manager.py`, `repo_tools.py`, and `ops_tools.py` all use the same exact-resume validation rules.
- [ ] Confirm canonical no-active baseline shape is identical everywhere it is materialized or synthesized.
- [ ] Confirm terminal-state handling is consistent across helper, verify, and commit-adjacent flows.
- [ ] Confirm top-level `next_action` is the primary continuation guide in:
  - [ ] helper paths
  - [ ] verify paths
  - [ ] summary paths
  - [ ] response surfaces
- [ ] Confirm helper metadata such as `session_id`, `task_id`, and mirrored nested fields are not used as canonical resume identity.

---

## 7. Verification checklist

### Exact-resume contract verification
- [ ] healthy materialized active state is accepted without rebuild
- [ ] malformed materialized active state is not accepted as healthy
- [ ] strict canonical no-active baseline is accepted
- [ ] malformed no-active variants are rejected

### Identity preservation verification
- [ ] existing active `tx_id` is reused exactly
- [ ] resume does not mint a replacement `tx_id`
- [ ] resume does not replace the active transaction with a heuristic candidate when exact active state is available

### Rebuild verification
- [ ] rebuild is used only when materialized state is missing, incomplete, or inconsistent
- [ ] ambiguous or drift-blocked rebuild results fail explicitly
- [ ] rebuilt state does not silently override healthy materialized state

### Helper bootstrap verification
- [ ] helper bootstrap does not normalize malformed canonical persistence into healthy active continuation
- [ ] helper bootstrap fails explicitly when deterministic exact continuation is unsafe

### Guidance consistency verification
- [ ] top-level canonical `next_action` is used consistently in helper and summary outputs
- [ ] response surfaces do not fall back to status-only continuation when canonical `next_action` exists

---

## 8. Documentation sync tasks

### `docs/v0.6.0/implementation-notes/p2-t03-exact-resume-summary.md`
- [ ] update workstream status after code changes
- [ ] record actual implementation decisions for helper bootstrap hardening
- [ ] record verification evidence for strict no-active baseline acceptance
- [ ] record whether any rebuild ambiguity handling was tightened

### `docs/v0.6.0/p2-t03.json`
- [ ] review whether `expected_outputs` should mention strict no-active baseline hardening
- [ ] review whether acceptance evidence should mention helper bootstrap safety explicitly
- [ ] keep wording aligned with `REQ-P2-EXACT-RESUME` without expanding scope

---

## 9. Exit criteria

This file-by-file remediation breakdown can be considered implemented when all of the following are true:

- strict canonical no-active baseline handling is shared across resume-related runtime surfaces
- malformed or ambiguous canonical persistence fails explicitly rather than being normalized
- helper bootstrap no longer bypasses exact-resume safety rules
- top-level canonical `next_action` is the primary continuation guide across relevant surfaces
- rebuild remains fallback-only and does not replace healthy exact active continuation
- `p2-t03` remaining gaps are closed without leaking into `p2-t04`
