# Implementation Plan: 0.5.2 Align `.rules`, generated rules, and tool responses for commit/finalize workflow

## Objectives
- Make the commit/finalize workflow contract explicit for AI agents that follow `.rules` and tool responses.
- Eliminate ambiguity about the difference between `committed` and terminal `done`.
- Keep canonical `.rules`, generated `.rules`, and workflow-driving tool responses aligned.
- Preserve the existing two-stage lifecycle model while making it easier for agents to act correctly.
- Prevent agents from leaving unintended non-terminal active transactions after successful commit helpers.

## Background
The AgentOps workflow model is primarily defined for agents by:

- repository `.rules`,
- the rules content generated into initialized workspaces by `zed-agentops-init.sh`,
- and the response payloads returned by workflow-driving MCP tools.

This is a machine-facing contract, not a human-facing documentation problem.

The current transaction model already distinguishes between:

- `verified`
- `committed`
- `done`

That distinction is meaningful and already reflected in the runtime state machine. In particular:

- commit helpers advance the workflow through verify and commit,
- `ops_end_task` is the terminal lifecycle helper,
- and a transaction remains active until it reaches `done` or `blocked`.

The problem is that the machine contract is not explicit enough for agents at the point where commit succeeds but terminal closure has not yet happened.

## Problem Statement
Today, a successful `commit_if_verified` call can leave canonical state in a form like:

- `active_tx.status = committed`
- `active_tx.phase = committed`
- `active_tx.next_action = tx.end.done`

This is a valid non-terminal state, but the current workflow contract does not make it explicit enough that:

1. commit success is not the same as terminal completion,
2. `committed` is still an active transaction state,
3. the next required action is to emit terminal completion,
4. and the caller should still execute `ops_end_task(status="done")`.

This creates a mismatch across three layers:

- `.rules` implies a staged work loop, but does not spell out the post-commit follow-up strongly enough,
- generated `.rules` must communicate the same contract to initialized workspaces,
- tool responses such as `commit_if_verified` and `repo_commit` do not currently surface enough canonical workflow guidance.

As a result, agents can incorrectly infer that “commit succeeded” means “ticket is finished,” even though the canonical transaction state still requires explicit closure.

## Scope

### In scope
- Clarify canonical `.rules` around post-commit non-terminal state.
- Keep generated `.rules` synchronized with the same clarified contract.
- Expand workflow-driving tool responses so agents can infer required follow-up actions.
- Add tests that verify alignment between rules text, generated rules, tool responses, and canonical state.
- Preserve the current transaction model while improving machine-actionable clarity.

### Out of scope
- Redesigning the transaction engine.
- Collapsing `committed` and `done` into one state.
- Replacing `ops_end_task` with a different terminal mechanism.
- Moving agent behavior expectations into README.
- Broad refactors unrelated to workflow contract alignment.

## Design Principles
The 0.5.2 work should follow these principles:

1. **Preserve the state machine**
   - `committed` remains a meaningful non-terminal state.
   - `done` remains the explicit terminal success state.

2. **Prefer explicit machine contracts**
   - Agents should not need to infer lifecycle semantics from ambiguous success payloads.
   - Rules and tool responses should state the required next action clearly.

3. **Keep one canonical rules contract**
   - Repository `.rules`, generated rules, and fallback rules must describe the same workflow.

4. **Add guidance, do not remove compatibility**
   - Existing success fields should remain where practical.
   - New workflow fields should be additive and backward-compatible.

## Implementation Strategy
The fix should not hide the distinction between `committed` and `done`.

Instead, it should make that distinction explicit and actionable by:

1. clarifying `.rules`,
2. regenerating bootstrap rules from the same clarified contract,
3. returning canonical workflow guidance from commit/verify tools.

In effect:

- `.rules` tells the agent what the workflow means,
- generated `.rules` ensures initialized workspaces enforce the same contract,
- tool responses tell the agent where it is in that workflow right now.

## Phases

### Phase 1: Clarify the canonical workflow contract in `.rules`
**Goals**
- Make post-commit follow-up requirements explicit.
- Remove ambiguity around `committed` versus `done`.

**Tasks**
- Update the Work loop section to explicitly state that:
  - successful commit helpers may leave the transaction in `committed`,
  - `committed` is non-terminal,
  - the transaction remains active until `done` or `blocked`,
  - `tx.end.done` is still required for successful terminal closure.
- Update the Tooling and/or Commit rules sections to state that:
  - `commit_if_verified` and `repo_commit` do not imply terminal completion by themselves,
  - callers must use canonical next action and transaction status to determine whether `ops_end_task` is still required.
- Make the post-commit follow-up rule explicit enough that an agent following `.rules` will not treat commit success as terminal success.

**Deliverables**
- Updated canonical `.rules` wording for commit/finalize workflow.
- Explicit machine-facing lifecycle guidance for post-commit follow-up.

---

### Phase 2: Keep generated rules synchronized with the canonical contract
**Goals**
- Ensure initialized workspaces receive the clarified rules contract.
- Prevent drift between repository rules and generated rules.

**Tasks**
- Update `workflow_rules.py` to include the clarified post-commit contract.
- Update `workflow_rules_fallback.txt` to match the same wording.
- Verify that `zed-agentops-init.sh` continues to distribute the same rules contract into workspace `.rules`.
- Confirm that there is no silent divergence between:
  - repository `.rules`
  - generated rules from `workflow_rules.py`
  - fallback rules content used for bootstrap

**Deliverables**
- Synchronized canonical and generated rules.
- Updated bootstrap-distributed rules matching the 0.5.2 contract.

---

### Phase 3: Expand workflow-driving tool responses
**Goals**
- Make tool results sufficient for agents to determine the next lifecycle action.
- Avoid ambiguous “success” responses that hide non-terminal state.

**Tasks**
- Review and update `commit_if_verified` response shape to include canonical workflow guidance, such as:
  - `ok`
  - `sha`
  - `message`
  - `tx_status`
  - `tx_phase`
  - `next_action`
  - `terminal`
  - `requires_followup`
  - optional follow-up hint fields
- Review and update `repo_commit` to return equivalent workflow-level fields.
- Review whether `repo_verify` should also return canonical workflow cues, such as:
  - resulting transaction status,
  - resulting phase,
  - next required action.
- Ensure the new fields are derived from canonical transaction state and do not contradict `tx_state`.

**Deliverables**
- Richer `commit_if_verified` response contract.
- Richer `repo_commit` response contract.
- Optionally aligned `repo_verify` response contract.

---

### Phase 4: Validate consistency between tool responses and canonical state
**Goals**
- Ensure response payloads reflect the real transaction state.
- Prevent agents from receiving misleading workflow signals.

**Tasks**
- Verify that successful commit helpers still leave the transaction in `committed` when `tx.end.done` has not yet been emitted.
- Ensure response fields such as `tx_status`, `tx_phase`, `next_action`, and `terminal` reflect the saved canonical state.
- Confirm that follow-up hints remain correct under:
  - verify pass,
  - verify fail,
  - commit success,
  - commit failure,
  - no-change commit conditions.
- Ensure terminal helpers continue to be the only path to terminal success or blocked termination.

**Deliverables**
- Canonical-state-consistent workflow responses.
- Clear separation between commit completion and terminal task completion.

---

### Phase 5: Add regression coverage for contract alignment
**Goals**
- Prevent future drift between rules and tool behavior.
- Ensure commit/finalize semantics remain machine-actionable.

**Tasks**
- Add tests for canonical `.rules` wording around:
  - non-terminal `committed`,
  - explicit `tx.end.done` requirement,
  - mandatory follow-up after successful commit helpers.
- Add tests for generated rules/fallback rules synchronization.
- Add tests for `commit_if_verified` response fields and their consistency with canonical state.
- Add tests for `repo_commit` response fields and follow-up guidance.
- Add tests for `repo_verify` response fields if expanded.
- Add tests that fail if commit helpers again return success without enough information to drive the next lifecycle step.

**Deliverables**
- Regression coverage for rules/tool-response alignment.
- Tests that protect the two-stage completion contract.

## Acceptance Criteria

### Rules clarity
- Canonical `.rules` explicitly states that successful commit helpers may leave the transaction in non-terminal `committed`.
- Canonical `.rules` explicitly states that terminal success still requires `tx.end.done`, typically through `ops_end_task(status="done")`.
- The rules explicitly instruct agents to use canonical next action and transaction status when deciding what to do after commit.

### Bootstrap consistency
- `workflow_rules.py` and `workflow_rules_fallback.txt` match the clarified canonical rules contract.
- `zed-agentops-init.sh` continues to write rules that reflect the same contract into initialized workspaces.

### Tool response clarity
- `commit_if_verified` responses make post-commit non-terminal state explicit.
- `repo_commit` responses make post-commit non-terminal state explicit.
- If adjusted, `repo_verify` responses clearly identify the next workflow step.
- Response payloads include enough workflow data for an agent to determine whether follow-up terminal closure is required.

### Transaction consistency
- Successful commit helpers that do not emit `tx.end.done` continue to leave the transaction in `committed`, not `done`.
- Tool responses do not contradict canonical `tx_state`.
- `ops_end_task` remains the explicit terminal close mechanism for success and blocked outcomes.

### Regression safety
- Tests verify alignment between canonical rules, generated rules, fallback rules, and tool responses.
- Tests fail if workflow-driving tools regress to ambiguous success responses.

## Risks

### Medium contract risk
Adding fields to tool responses may affect clients that assume minimal payloads.

**Mitigation**
- Prefer additive response fields.
- Preserve existing success keys where possible.
- Keep semantics backward-compatible while enriching workflow guidance.

### Medium synchronization risk
The change spans multiple rule surfaces plus tool responses, so drift is possible.

**Mitigation**
- Add explicit synchronization tests.
- Keep one canonical wording source and verify derived outputs against it.

### Low behavioral risk
The intended lifecycle behavior is already present in the state machine; the change primarily clarifies and surfaces it.

**Mitigation**
- Avoid altering terminal semantics.
- Keep the transaction model unchanged unless explicitly required.

## Validation Plan
After implementation, validation should include:

1. verification that canonical `.rules` contains explicit post-commit follow-up guidance,
2. verification that generated and fallback rules match the clarified contract,
3. successful `commit_if_verified` calls returning workflow-level guidance,
4. successful `repo_commit` calls returning workflow-level guidance,
5. consistency checks between response fields and saved `tx_state`,
6. regression test execution across rules and workflow tools.

## Ticket Breakdown

### Ticket `p1-t01`
**Title:** Clarify canonical `.rules` for post-commit non-terminal workflow  
**Priority:** P0  
**Summary:** Update `.rules` so agents are explicitly told that successful commit helpers may leave the transaction in `committed`, that this state is non-terminal, and that `ops_end_task(status="done")` is still required for terminal success.

### Ticket `p1-t02`
**Title:** Synchronize generated and fallback rules with the clarified commit/finalize contract  
**Priority:** P0  
**Summary:** Update `workflow_rules.py`, `workflow_rules_fallback.txt`, and the bootstrap-distributed rules path so initialized workspaces receive the same clarified workflow contract as the repository.

### Ticket `p2-t01`
**Title:** Expand `commit_if_verified` and `repo_commit` responses with canonical workflow guidance  
**Priority:** P1  
**Summary:** Add workflow-level response fields so agents can tell whether a transaction is terminal, what the current canonical status is, and what follow-up action is still required.

### Ticket `p2-t02`
**Title:** Align `repo_verify` responses with the staged workflow contract  
**Priority:** P2  
**Summary:** Evaluate and, if appropriate, expand `repo_verify` responses to include canonical workflow cues such as resulting status and next required action.

### Ticket `p3-t01`
**Title:** Add regression coverage for rules and tool-response alignment  
**Priority:** P1  
**Summary:** Add tests that verify canonical rules, generated rules, and workflow-driving tool responses all agree on the commit-to-finalize contract.

## Expected Outcome
After 0.5.2:

- agents following `.rules` will no longer confuse commit success with terminal task completion,
- initialized workspaces will receive the same clarified contract via generated `.rules`,
- commit and verify tool responses will expose enough canonical workflow state to guide next actions,
- and the existing strict resumability model will remain intact while becoming less ambiguous.

## Summary
Version 0.5.2 should resolve a workflow-contract ambiguity by aligning:

- canonical `.rules`,
- generated rules distributed by `zed-agentops-init.sh`,
- and workflow-driving tool responses

around the existing two-stage lifecycle model in which commit success may produce `committed` without yet producing terminal `done`.

The goal is not to change the model, but to make the model explicit and machine-actionable so agents can reliably finish the workflow without leaving unintended active transactions behind.