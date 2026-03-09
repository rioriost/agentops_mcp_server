# Draft for 0.5.4: make canonical workflow guidance machine-readable and agent-safe

## Background

Version 0.5.3 focused on transaction-log integrity and duplicate-`tx.begin` handling.

That work strengthens the canonical lifecycle by:

- keeping replay strict,
- rejecting invalid lifecycle history,
- and preserving resumability guarantees when the event log is healthy.

However, operational use still shows a separate problem: even when the canonical rules are correct and the server enforces many invariants, an AI agent can still make avoidable lifecycle mistakes because the guidance exposed by tool responses is not yet rich enough or consistent enough across the tool surface.

In practice, the system currently relies on a combination of:

- `.rules`,
- implicit tool behavior,
- error strings,
- and some workflow-aware helper responses.

This is close, but not yet strong enough for reliable, machine-driven lifecycle management across interruption, resume, verify, commit, and terminal completion flows.

## Problem

The current MCP workflow contract does not expose enough structured canonical state and recovery guidance in every relevant tool response for an AI agent to reliably maintain canonical transaction status without ambiguity.

The core issue is not that the lifecycle rules are missing.

The issue is that:

- some tools return rich workflow guidance,
- some tools return only a minimal success payload,
- some failures are expressed mainly as plain error strings,
- and the agent must still infer too much from natural-language rules and implementation details.

As a result, an agent may still mis-handle cases such as:

- attempting lifecycle work after a terminal transaction,
- attempting commit helper operations when canonical state is already terminal,
- starting work when a non-terminal active transaction should be resumed,
- or failing to explicitly close a non-terminal `committed` transaction after helper success.

## Why this matters

The AgentOps model depends on the agent being able to act correctly from canonical local state, not from guesswork.

For resumability to be dependable, the workflow contract must let an agent answer questions like:

- Is there an active transaction?
- Is it terminal or non-terminal?
- What is the canonical status right now?
- What is the canonical phase right now?
- What is the next required action?
- Is follow-up mandatory?
- Which tool should be called next?
- Is the current failure recoverable?
- Should the agent resume, repair, or begin a new transaction?

If those answers are not consistently exposed in machine-readable form, then the workflow remains partially dependent on natural-language interpretation and hidden implementation knowledge.

That weakens:

- resumability,
- interrupt-safe execution,
- deterministic lifecycle handling,
- and confidence that different agents or future prompts will behave the same way.

## Goal

For 0.5.4, make workflow guidance consistently machine-readable across the MCP surface so that an AI agent can correctly maintain canonical transaction status using `.rules` plus tool responses, without relying on hidden assumptions.

The release should improve the contract so that:

- lifecycle-affecting tools return canonical state guidance consistently,
- state-related failures return structured recovery information,
- helper tools clearly indicate whether more lifecycle work is required,
- and agents can distinguish terminal, non-terminal, resumable, blocked, and repair-needed situations deterministically.

## Desired outcome

After 0.5.4:

- all lifecycle-relevant tool responses expose enough structured canonical guidance for agents to make the next workflow decision safely,
- success responses consistently indicate the resulting canonical status and required follow-up,
- error responses consistently indicate why the action failed and what the agent should do next,
- the difference between non-terminal `committed` and terminal `done` remains explicit and machine-readable,
- and routine agent operation no longer depends on guessing lifecycle state from sparse payloads or raw error strings.

## Scope

### In scope

- defining a consistent machine-readable workflow guidance contract,
- extending success responses for lifecycle-affecting tools,
- extending error responses for state/lifecycle failures,
- clarifying helper follow-up semantics in responses,
- aligning the implementation with `.rules`,
- and adding regression coverage for machine-readable guidance.

### Out of scope

- redesigning the transaction/event model,
- weakening strict lifecycle invariants,
- replacing `.rules` with a different governance mechanism,
- broad changes unrelated to lifecycle guidance,
- or making malformed/invalid transaction history appear healthy.

## Non-goals

This draft does not propose:

- removing strict replay or integrity failures,
- hiding terminal-state violations,
- collapsing `status`, `phase`, and `next_action` into a less expressive model,
- or replacing explicit lifecycle completion with implicit completion.

The goal is to make the existing workflow easier for agents to follow correctly, not to simplify away the lifecycle model.

## Observed weakness in the current contract

The current system already contains useful workflow information in some places.

For example, verify and commit helpers can expose:

- `tx_status`,
- `tx_phase`,
- `next_action`,
- `terminal`,
- `requires_followup`,
- and `followup_tool`.

That is good and should be preserved.

The weakness is that this guidance is not yet consistently available across all lifecycle-relevant tools.

In particular, some lifecycle wrapper tools currently return only minimal payloads such as:

- `ok`,
- `event`,
- and `payload`.

That forces the agent to infer the resulting canonical lifecycle state rather than reading it directly from the response.

Likewise, some important failures are currently surfaced mainly through plain error strings such as:

- `tx.begin required before other events`,
- `event after terminal`,
- `file intent already exists for path`.

These messages are useful for humans, but they are not yet a complete machine-readable recovery contract.

## Core 0.5.4 requirement

The central requirement for 0.5.4 is:

> Every tool that affects lifecycle progression, validates lifecycle state, or can fail due to canonical state constraints must return enough structured information for an agent to determine the correct next step without hidden assumptions.

This should apply to both success and failure results.

## Proposed 0.5.4 changes

## A. Standardize canonical workflow guidance in success responses

All lifecycle-relevant success responses should expose a shared workflow guidance shape.

At minimum, that shape should include:

- `canonical_status`
- `canonical_phase`
- `next_action`
- `terminal`
- `requires_followup`
- `followup_tool`
- `active_tx_id`
- `active_ticket_id`

Where applicable, the response should also include:

- `current_step`
- `verify_status`
- `commit_status`
- `integrity_status`

The names may vary if needed for compatibility, but the semantics must be consistent across tools.

### Tools that should return this guidance

At minimum, this should be added or normalized for:

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

### Requirements

- Success responses must describe the resulting canonical state after the tool completes.
- The guidance must reflect canonical state, not inferred client-side assumptions.
- When a helper leaves the transaction non-terminal, the response must say so explicitly.
- If additional lifecycle completion is required, the response must indicate that explicitly.

## B. Standardize structured recovery guidance in failure responses

Lifecycle- or state-related failures should return machine-readable error information in addition to a human-readable message.

At minimum, structured failures should include:

- `ok: false`
- `error_code`
- `reason`
- `recoverable`
- `recommended_next_tool`
- `recommended_action`
- `canonical_status` when known
- `canonical_phase` when known
- `next_action` when known
- `terminal` when known
- `active_tx_id` when known
- `active_ticket_id` when known

Where integrity or replay issues are involved, include:

- `integrity_status`
- `blocked`
- `rebuild_warning`
- `rebuild_invalid_seq`
- `rebuild_observed_mismatch`

### Requirements

- The response must let an agent distinguish between:
  - uninitialized state,
  - no active transaction,
  - active non-terminal transaction requiring resume,
  - terminal transaction,
  - integrity-blocked state,
  - and invalid operation ordering.
- Human-readable error strings may remain, but structured fields must be the canonical contract for agent decision-making.
- Similar failure modes should use stable error codes rather than only free-form strings.

## C. Make helper follow-up semantics explicit and uniform

Commit/verify helpers already expose some workflow guidance, but 0.5.4 should make that contract explicit and uniform.

### Required behavior

- If a helper completes verify but not commit, its response must indicate the resulting canonical state and next required action.
- If a helper completes commit but leaves the lifecycle in non-terminal `committed`, its response must explicitly indicate:
  - `terminal: false`
  - `canonical_status: committed`
  - `next_action: tx.end.done` or equivalent
  - `requires_followup: true`
  - `followup_tool: ops_end_task`
- Helper success must never imply terminal completion unless canonical status is actually terminal.

### Goal

An agent should be able to treat helper responses as authoritative workflow guidance without re-deriving lifecycle semantics from `.rules` text.

## D. Clarify the relationship between `status`, `phase`, and `next_action`

The current model uses `status`, `phase`, and `next_action`, but their distinct roles must be easier for agents to consume correctly.

### Requirements

- The server should define and consistently apply the meaning of each field:
  - `status`: canonical lifecycle status
  - `phase`: canonical workflow phase
  - `next_action`: the next expected lifecycle action
- Tool responses should not leave the agent guessing which field is authoritative for the next step.
- If `phase` is derived from `status` in some situations, that should be made explicit in behavior and tests.
- Terminal detection must remain consistent:
  - `done` and `blocked` are terminal
  - `committed` is non-terminal unless explicitly ended

## E. Expose active transaction identity consistently

Agents need a stable way to know whether they should resume existing work or begin new work.

### Requirements

Responses should expose the canonical active identity clearly, including:

- `active_tx_id`
- `active_ticket_id`
- whether an active transaction exists
- whether it is resumable
- whether starting a new ticket is allowed

Where appropriate, also expose:

- `can_start_new_ticket`
- `resume_required`

This should make the resume-vs-begin decision machine-readable rather than purely textual.

## F. Improve tool responses for begin/resume conflicts

One of the common failure cases is confusion between:

- beginning a new transaction,
- resuming an existing non-terminal transaction,
- and acting after a terminal transaction.

### Requirements

When a begin-like operation is rejected, the response should clearly distinguish:

- no active transaction exists and `tx.begin` is required,
- an active non-terminal transaction exists and must be resumed,
- a terminal transaction exists and a new begin is allowed only with a new task context,
- or canonical integrity drift prevents safe lifecycle progression.

This distinction must be machine-readable and stable enough for an agent to branch on safely.

## G. Preserve strictness while improving agent operability

This release should not weaken invariants.

Instead, it should make strictness easier to operate correctly.

### Requirements

- Invalid event order must still be rejected.
- Terminal-state violations must still be rejected.
- File-intent ordering must still be enforced.
- Integrity drift must still block unsafe canonical-state operations.
- The improvement must come from richer responses and clearer contracts, not from relaxing canonical correctness.

## H. Add regression coverage for workflow guidance contracts

The new machine-readable contract must be tested explicitly.

### Tests should cover

- lifecycle wrapper success responses include canonical guidance fields,
- helper success responses correctly report follow-up requirements,
- error responses include structured recovery guidance,
- terminal vs non-terminal distinctions remain correct,
- `committed` remains non-terminal until explicit end,
- resume-vs-begin conflict cases produce distinct, machine-readable outcomes,
- integrity-blocked cases surface structured blocked guidance,
- and regression tests fail if responses fall back to ambiguous minimal payloads.

## Acceptance criteria

The 0.5.4 work should satisfy all of the following.

### Success response contract
- All lifecycle-relevant tools return structured canonical workflow guidance.
- The guidance is consistent across tools.
- The resulting canonical state is exposed after successful lifecycle operations.
- Helper responses explicitly indicate whether follow-up lifecycle completion is still required.

### Failure response contract
- Lifecycle/state failures return machine-readable recovery guidance.
- Error codes are stable enough for agent branching.
- Agents can distinguish begin-required, resume-required, terminal, and integrity-blocked cases without parsing only free-form prose.
- Structured failure responses include recommended next action or tool when applicable.

### Canonical semantics
- `done` and `blocked` remain terminal.
- `committed` remains non-terminal until explicit terminal completion.
- `next_action` remains authoritative and is exposed consistently.
- Success and failure responses do not imply a healthier or more complete lifecycle state than canonical state actually supports.

### Resume safety
- Agents can determine from tool responses whether a new ticket may be started.
- Agents can determine when an existing transaction must be resumed.
- Agents can determine when explicit terminal closure is still required after verify/commit helper success.

### Regression protection
- Tests fail if lifecycle tools stop returning canonical guidance.
- Tests fail if helper responses stop exposing follow-up requirements.
- Tests fail if structured recovery guidance regresses to ambiguous string-only failures.
- Tests fail if terminal and non-terminal lifecycle distinctions are misreported.

## Design principles

## 1. Canonical state remains the source of truth

Responses must reflect canonical transaction state, not client convenience or guessed transitions.

## 2. Machine-readable guidance is part of the public contract

If an agent must act on a lifecycle rule, the response contract should expose it directly.

## 3. Strictness should be explicit, not opaque

When an operation is rejected, the server should say not only that it failed, but also what kind of state the agent is in and what to do next.

## 4. Follow-up obligations must be visible

If a tool leaves the workflow non-terminal, the response must make the remaining obligation explicit.

## 5. Resume decisions must be deterministic

An agent should be able to decide between begin, resume, repair, or terminal close from structured response data plus `.rules`, without hidden implementation knowledge.

## Possible implementation directions

The exact implementation is flexible, but 0.5.4 will likely require work in areas such as:

- shared response-building helpers for workflow guidance,
- normalization of success payloads across lifecycle tools,
- structured error/result wrappers for lifecycle/state failures,
- possible updates to public tool descriptions or README guidance,
- and test fixtures/assertions for the new response contract.

## Open questions

The implementation should resolve the following questions explicitly:

1. What exact field names should be standardized across all workflow-aware responses?
2. Should structured failures be returned as normal `ok: false` payloads more often, instead of raising raw exceptions?
3. Which fields are mandatory across all lifecycle tools, and which are optional by context?
4. How should backward compatibility be handled for existing clients expecting minimal payloads?
5. Should summary/resume tools expose the same workflow guidance schema or a closely related one?

## Summary

Version 0.5.4 should make the canonical workflow contract safer for AI agents by turning lifecycle guidance from partially implicit behavior into consistently structured, machine-readable responses.

The release is successful if an agent can use `.rules` plus tool responses to:

- identify the active canonical state,
- understand whether it is terminal,
- know what action must come next,
- know whether follow-up is required,
- and recover from lifecycle-related failures without guessing.

That is the core requirement for dependable, resumable, interruption-safe agent operation.