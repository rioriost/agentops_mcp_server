# Implementation Plan: 0.5.4 Make canonical workflow guidance machine-readable and agent-safe

## Objectives
- Standardize machine-readable workflow guidance across lifecycle-relevant MCP tool responses.
- Make success responses expose resulting canonical transaction state explicitly.
- Make failure responses expose structured recovery guidance explicitly.
- Preserve strict canonical lifecycle invariants while reducing agent guesswork.
- Clarify follow-up obligations after verify/commit helper success.
- Add regression coverage so workflow guidance remains stable for AI agents and clients.

## Background
Version 0.5.3 focused on transaction-log integrity and duplicate `tx.begin` handling.

That work improved lifecycle safety by:
- preserving strict replay,
- rejecting invalid lifecycle history,
- and protecting canonical resumability guarantees.

However, operational use still shows a contract gap at the response level.

Today, the server already contains strong lifecycle rules and state validation, but the exposed tool responses are uneven:
- some tools return workflow-aware guidance,
- some tools return only minimal payloads,
- and some lifecycle failures are surfaced mainly as human-readable error strings.

This means an AI agent still has to infer too much from:
- `.rules`,
- partial response payloads,
- and implicit implementation behavior.

For interruption-safe resumability, that is not strong enough.

## Problem Statement
The current workflow contract does not consistently expose enough structured canonical guidance for an AI agent to determine the correct next step without hidden assumptions.

In particular:
- lifecycle wrapper tools may succeed without returning the resulting canonical status/phase/next action,
- helper tools expose more guidance, but not yet as a clearly standardized contract,
- and failures like begin-order violations or terminal-state violations are not always represented as structured recovery outcomes.

As a result, agents can still mis-handle:
- begin vs resume decisions,
- terminal vs non-terminal transaction handling,
- follow-up requirements after helper success,
- and lifecycle recovery after state-related failures.

## Scope

### In scope
- Defining a shared workflow-guidance response shape for lifecycle-relevant tools.
- Extending success responses to expose resulting canonical state consistently.
- Extending failure responses to expose structured recovery guidance consistently.
- Clarifying response semantics for `status`, `phase`, `next_action`, and terminality.
- Standardizing follow-up signaling after verify/commit helpers.
- Adding regression tests for success and failure guidance contracts.
- Updating docs and contract-facing descriptions where necessary.

### Out of scope
- Redesigning the transaction/event model.
- Weakening strict lifecycle validation.
- Replacing `.rules`.
- Broad refactors unrelated to lifecycle guidance.
- Treating invalid canonical history as healthy state.

## Desired Outcome
After 0.5.4:
- agents can determine the current canonical lifecycle state directly from tool responses,
- agents can tell whether they must begin, resume, repair, commit, or explicitly end a transaction,
- helpers explicitly report whether more lifecycle work remains,
- failure responses become machine-readable enough for deterministic branching,
- and canonical status remains strict without becoming opaque.

## Design Principles

### 1. Canonical state remains authoritative
Responses must reflect canonical transaction state, not client convenience or inferred guesses.

### 2. Machine-readable guidance is part of the contract
If an agent must decide what to do next, the response should expose that directly.

### 3. Strictness must remain explicit
Invalid ordering, terminal-state violations, and integrity-blocked states should still fail, but in a way that is structured and actionable.

### 4. Non-terminal `committed` must remain explicit
Commit helper success must not be confused with terminal completion.

### 5. Resume decisions must be deterministic
Agents should be able to distinguish:
- no active transaction,
- active resumable transaction,
- terminal transaction,
- integrity-blocked state,
- and invalid operation ordering
from structured response data.

## Proposed Response Contract

## Shared success guidance
Lifecycle-relevant success responses should expose a normalized set of fields.

### Required fields
- `ok`
- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `requires_followup`
- `followup_tool`
- `active_tx_id`
- `active_ticket_id`

### Contextual fields
When applicable, also expose:
- `current_step`
- `verify_status`
- `commit_status`
- `integrity_status`
- `can_start_new_ticket`
- `resume_required`

### Behavioral requirements
- These fields must describe the resulting canonical state after the tool completes.
- Guidance must be internally consistent across tools.
- Missing fields should be omitted only when truly unknown, not because the tool is returning a minimal payload.

## Shared failure guidance
Lifecycle- and state-related failures should expose a normalized structured failure result.

### Required fields
- `ok: false`
- `error_code`
- `reason`
- `recoverable`
- `recommended_next_tool`
- `recommended_action`

### Contextual fields
When known, also expose:
- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `active_tx_id`
- `active_ticket_id`
- `current_step`
- `integrity_status`
- `blocked`
- `rebuild_warning`
- `rebuild_invalid_seq`
- `rebuild_observed_mismatch`

### Behavioral requirements
- Similar failure modes should use stable error codes.
- Human-readable strings may remain, but should not be the only decision surface.
- Failure results should let agents branch without parsing prose alone.

## Lifecycle tools in scope
The following tools should be aligned with the new contract:

- `ops_start_task`
- `ops_update_task`
- `ops_end_task`
- `ops_add_file_intent`
- `ops_update_file_intent`
- `ops_complete_file_intent`
- `ops_capture_state`
- `repo_verify`
- `repo_commit`
- `commit_if_verified`

## Implementation Strategy

### Phase 1: Define the workflow-guidance contract
**Goals**
- Decide the exact response schema.
- Establish which fields are mandatory vs contextual.
- Make the contract consistent across lifecycle success and failure paths.

**Tasks**
- Define a canonical success-guidance shape.
- Define a canonical failure-guidance shape.
- Decide field naming for:
  - canonical status,
  - canonical phase,
  - next action,
  - terminality,
  - follow-up requirements,
  - and active transaction identity.
- Decide whether backward-compatible legacy fields remain alongside new fields.
- Define stable error-code categories for common lifecycle failures.

**Deliverables**
- A documented response contract for lifecycle-aware tools.
- A clear field-by-field semantic definition.

**Acceptance for phase**
- The team can point to a single authoritative contract for lifecycle response guidance.
- The contract covers both success and failure paths.

---

### Phase 2: Introduce shared response-building helpers
**Goals**
- Avoid duplicating workflow-guidance logic in every tool.
- Make guidance generation consistent and easier to test.

**Tasks**
- Add internal helpers for building standardized success responses.
- Add internal helpers for building standardized failure responses.
- Centralize derivation of:
  - terminal vs non-terminal state,
  - follow-up requirements,
  - active transaction identity,
  - and resume/new-ticket guidance.
- Ensure helpers read canonical state rather than re-deriving from ad hoc assumptions.

**Deliverables**
- Shared response-building utilities.
- Reduced per-tool duplication for workflow metadata.

**Acceptance for phase**
- Multiple tools use the same response-building logic.
- Guidance fields are generated uniformly.

---

### Phase 3: Normalize lifecycle wrapper success responses
**Goals**
- Make lifecycle wrapper tools expose resulting canonical state explicitly.

**Tasks**
- Update:
  - `ops_start_task`
  - `ops_update_task`
  - `ops_end_task`
  - `ops_add_file_intent`
  - `ops_update_file_intent`
  - `ops_complete_file_intent`
  - `ops_capture_state`
- Ensure each successful response includes:
  - canonical status,
  - canonical phase,
  - next action,
  - terminal flag,
  - follow-up fields,
  - and active transaction identity.
- Ensure `ops_end_task` accurately reports terminal completion.
- Ensure `ops_capture_state` reflects integrity and blocked state consistently.

**Deliverables**
- Uniform success payloads for lifecycle wrapper tools.

**Acceptance for phase**
- Lifecycle wrapper tools no longer return success results that force the agent to infer canonical state from minimal payloads alone.

---

### Phase 4: Normalize helper success responses and follow-up semantics
**Goals**
- Make verify/commit helper responses explicit about remaining obligations.

**Tasks**
- Review and normalize:
  - `repo_verify`
  - `repo_commit`
  - `commit_if_verified`
- Ensure helper responses clearly report:
  - resulting canonical status,
  - next action,
  - whether the transaction is terminal,
  - whether follow-up is required,
  - and which tool should be called next.
- Preserve explicit semantics that:
  - `committed` is non-terminal,
  - helper success does not imply `done`,
  - and explicit lifecycle closure may still be required.

**Deliverables**
- Standardized helper response contract.
- Clear machine-readable indication of follow-up obligations.

**Acceptance for phase**
- An agent can determine from helper success alone whether it must still call terminal lifecycle completion.

---

### Phase 5: Normalize lifecycle/state failure responses
**Goals**
- Make failures actionable and machine-readable.

**Tasks**
- Identify common lifecycle/state failure families, such as:
  - begin required,
  - resume required,
  - event after terminal,
  - cannot verify terminal transaction,
  - file intent already exists,
  - file intent missing,
  - verify-pass prerequisite violations,
  - integrity drift / blocked rebuild.
- Assign stable error codes.
- Convert or wrap failure paths so they expose structured guidance.
- Ensure failures distinguish:
  - no active transaction,
  - active resumable transaction,
  - terminal transaction,
  - integrity-blocked state,
  - and invalid ordering.

**Deliverables**
- Structured failure contract across key lifecycle tools.
- Stable error-code mapping for agent branching.

**Acceptance for phase**
- Agents can branch on structured failure fields without depending solely on string matching.

---

### Phase 6: Clarify `status`, `phase`, and `next_action`
**Goals**
- Remove ambiguity around the meaning of core lifecycle fields.

**Tasks**
- Audit lifecycle state-setting paths for consistency.
- Confirm and document:
  - what `status` means,
  - what `phase` means,
  - what `next_action` means,
  - and how terminality is computed.
- Ensure response builders do not expose contradictory combinations.
- Verify `committed`, `done`, and `blocked` semantics remain explicit and correct.

**Deliverables**
- Consistent semantics for status/phase/next_action in implementation and responses.
- Tests ensuring correct terminal/non-terminal classification.

**Acceptance for phase**
- Tools do not return contradictory lifecycle guidance.
- Terminality is computed consistently.

---

### Phase 7: Add regression coverage
**Goals**
- Lock in the contract so it remains safe for agents.

**Tasks**
- Add tests for lifecycle wrapper success responses.
- Add tests for helper follow-up semantics.
- Add tests for structured lifecycle/state failures.
- Add tests for:
  - begin-required vs resume-required distinction,
  - terminal vs non-terminal reporting,
  - `committed` remaining non-terminal,
  - integrity-blocked guidance,
  - active transaction identity reporting,
  - and can-start/resume-required signaling.
- Add regression tests that fail if tools revert to ambiguous minimal lifecycle responses.

**Deliverables**
- A regression suite protecting the workflow-guidance contract.

**Acceptance for phase**
- Contract regressions are caught automatically.
- Tests encode machine-readable guidance expectations, not just human-readable strings.

---

### Phase 8: Update documentation and contract-facing descriptions
**Goals**
- Keep user-facing and client-facing documentation aligned with implementation.

**Tasks**
- Update plan/docs/spec-facing material as needed.
- Update tool descriptions if response semantics need stronger public wording.
- Clarify the expectation that clients and agents should use structured response guidance.
- Document the difference between:
  - helper completion,
  - non-terminal `committed`,
  - and terminal lifecycle completion.

**Deliverables**
- Updated documentation aligned with 0.5.4 behavior.

**Acceptance for phase**
- Documentation does not lag behind the implemented response contract.

## Candidate Work Areas
Likely implementation areas include:
- lifecycle wrapper tool implementation,
- verify/commit helper implementation,
- state and workflow guidance helpers,
- repo/state-facing tool response builders,
- tests covering lifecycle success/failure contract behavior,
- and docs describing the machine-readable contract.

## Ticket Breakdown

### P1-T1: Define workflow-guidance response schema
**Goal**
Create the authoritative 0.5.4 contract for lifecycle-aware success and failure responses.

**Inputs**
- `docs/draft_0.5.4.md`
- current lifecycle tool behavior
- existing helper response fields

**Outputs**
- agreed response schema
- field semantics
- stable error-code outline

**Acceptance criteria**
- mandatory and contextual fields are defined
- success and failure contracts are both covered
- field semantics for `status`, `phase`, `next_action`, and terminality are explicit

---

### P1-T2: Add shared response-building utilities
**Goal**
Centralize canonical guidance generation.

**Inputs**
- response schema from `P1-T1`

**Outputs**
- shared success/failure response builders
- helper logic for terminal/follow-up/identity derivation

**Acceptance criteria**
- multiple tools use the shared builders
- duplicated workflow-guidance logic is reduced

---

### P1-T3: Normalize lifecycle wrapper success responses
**Goal**
Make lifecycle wrapper tools return resulting canonical state explicitly.

**Inputs**
- shared builders
- lifecycle wrapper tools

**Outputs**
- standardized success payloads for wrapper tools

**Acceptance criteria**
- wrapper tool success responses include canonical guidance fields
- agents no longer need to infer resulting state from minimal payloads alone

---

### P2-T1: Normalize helper success and follow-up semantics
**Goal**
Make helper responses explicit about remaining lifecycle obligations.

**Inputs**
- existing helper behavior
- shared builders

**Outputs**
- standardized helper responses
- explicit non-terminal `committed` follow-up signaling

**Acceptance criteria**
- helper responses expose follow-up requirements consistently
- `ops_end_task` follow-up is clearly indicated when required

---

### P2-T2: Normalize structured lifecycle/state failures
**Goal**
Make key lifecycle failures machine-readable and actionable.

**Inputs**
- existing failure paths
- error families identified in 0.5.4 draft

**Outputs**
- structured failure responses
- stable error codes
- recommended next-tool/action guidance

**Acceptance criteria**
- begin-required, resume-required, terminal, and integrity-blocked cases are distinguishable by structured fields
- failures are actionable without relying only on prose

---

### P2-T3: Clarify and enforce lifecycle field semantics
**Goal**
Ensure `status`, `phase`, `next_action`, and terminality remain consistent across responses.

**Inputs**
- shared contract
- lifecycle state-setting code

**Outputs**
- aligned lifecycle semantics in implementation
- tests for non-contradictory guidance

**Acceptance criteria**
- no contradictory canonical guidance is returned
- `done`/`blocked` remain terminal
- `committed` remains non-terminal

---

### P3-T1: Add regression tests for workflow guidance contract
**Goal**
Protect the new machine-readable response contract from regression.

**Inputs**
- implemented success/failure schemas
- normalized tool behavior

**Outputs**
- test coverage for:
  - success guidance fields,
  - structured failures,
  - helper follow-up semantics,
  - active transaction identity,
  - and resume/new-ticket guidance

**Acceptance criteria**
- tests fail if lifecycle-aware tools regress to ambiguous responses
- contract behavior is verified across representative lifecycle flows

---

### P3-T2: Update docs and contract-facing guidance
**Goal**
Align docs and public descriptions with 0.5.4 behavior.

**Inputs**
- final implementation
- response schema

**Outputs**
- updated docs
- updated tool/contract descriptions where needed

**Acceptance criteria**
- docs match implemented behavior
- helper follow-up and terminal-completion semantics are clearly documented

## Acceptance Criteria

### Success response contract
- All lifecycle-relevant tools return structured canonical workflow guidance.
- Guidance is consistent across tools.
- Success responses expose resulting canonical state after the operation completes.
- Helper responses explicitly state whether more lifecycle work remains.

### Failure response contract
- Lifecycle/state failures expose structured recovery guidance.
- Stable error codes exist for common lifecycle failure families.
- Agents can distinguish begin-required, resume-required, terminal, and integrity-blocked cases from structured data.
- Failure responses expose recommended next tool or action when applicable.

### Canonical semantics
- `done` and `blocked` remain terminal.
- `committed` remains non-terminal until explicitly ended.
- `next_action` remains authoritative and consistently exposed.
- Responses do not imply healthier lifecycle state than canonical state actually supports.

### Resume safety
- Agents can determine whether a new ticket may be started.
- Agents can determine whether an existing transaction must be resumed.
- Agents can determine whether terminal closure is still required after helper success.

### Regression safety
- Tests fail if lifecycle tools stop returning canonical guidance.
- Tests fail if helper responses stop exposing follow-up requirements.
- Tests fail if lifecycle failures regress to ambiguous string-only outcomes.
- Tests fail if terminal/non-terminal distinctions are misreported.

## Risks

### 1. Backward-compatibility drift
Existing clients may expect minimal payloads or current field names.

**Mitigation**
- Preserve existing fields where practical.
- Add new canonical fields alongside old ones before removing anything.

### 2. Inconsistent field population
Some tools may expose fields with slightly different semantics.

**Mitigation**
- Use shared response builders.
- Add cross-tool regression tests.

### 3. Partial normalization
If only helper tools or only wrapper tools are normalized, ambiguity remains.

**Mitigation**
- Treat 0.5.4 as contract-wide work, not isolated helper cleanup.

### 4. Overexposing inferred state
Responses could accidentally expose guessed rather than canonical state.

**Mitigation**
- Build guidance from canonical state and validated workflow helpers.
- Keep integrity-blocked behavior explicit.

## Open Questions
1. Which exact field names should be standardized in the final response schema?
2. Should lifecycle-related failures prefer structured `ok: false` payloads over raising raw exceptions in more cases?
3. Which fields are mandatory for every lifecycle-aware tool, and which are context-specific?
4. How much backward compatibility is required for existing clients?
5. Should summary/resume tools adopt the same response schema or a closely related derivative?

## Summary
Version 0.5.4 should make the workflow contract safer for AI agents by turning lifecycle guidance from partially implicit behavior into a consistent machine-readable response surface.

The release succeeds if an agent can use `.rules` plus tool responses to determine:
- what the canonical state is,
- whether it is terminal,
- what action must come next,
- whether more lifecycle work is required,
- and how to recover from lifecycle/state failures
without guessing.