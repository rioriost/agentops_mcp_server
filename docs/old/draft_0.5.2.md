# Draft for 0.5.2: align `.rules`, bootstrap-generated rules, and tool responses for commit/finalize workflow

## Background

The AgentOps operating model is driven primarily by:

- the canonical workflow contract in `.rules`,
- the generated rules written into initialized workspaces by `zed-agentops-init.sh`,
- and the MCP tool responses that agents use to decide what to do next.

In this model, README documents are not the primary control surface for agents. Agents are expected to:

1. follow `.rules`,
2. invoke tools according to that workflow,
3. and adjust their next action based on tool responses and canonical transaction state.

That means workflow correctness depends less on human-facing documentation and more on whether these three machine-relevant surfaces agree:

- canonical `.rules`,
- bootstrap-generated `.rules`,
- tool response contracts.

Version 0.5.1 improved bootstrap reliability by making `zed-agentops-init.sh` resolve workflow rule assets relative to the script path. That work fixed how `.rules` gets written, but it did not yet resolve a separate workflow-contract mismatch around commit completion and terminal task closure.

## Problem

The current workflow contract around commit completion is underspecified for agents.

### Observed behavior

The current `commit_if_verified` helper:

- runs verification,
- records verify pass/fail,
- emits commit start/done/fail events,
- performs the Git commit,
- and leaves the active transaction in a `committed` state with `next_action` typically set to `tx.end.done`.

However, it does not itself emit `tx.end.done`, and therefore does not move the active transaction into terminal `done`.

This means that after a successful commit:

- the repository state is committed,
- the canonical transaction is not terminal,
- the active transaction still exists,
- and the correct next action is still to close the transaction explicitly.

### Why this is a problem

This is not inherently wrong if the workflow contract clearly says so.

The current issue is that the contract is not sufficiently explicit across the machine-relevant surfaces that matter for agents:

- `.rules` describes a staged workflow ending in `done`,
- `ops_end_task` is the tool that actually emits terminal lifecycle completion,
- but `commit_if_verified` returns only commit-oriented data and does not clearly instruct the caller that a terminal close is still required.

As a result, an agent can reasonably do the following:

1. follow `.rules` up to verification and commit,
2. call `commit_if_verified`,
3. see that commit succeeded,
4. infer that the ticket is effectively complete,
5. and then accidentally leave a non-terminal active transaction behind.

That creates resumability friction because later logic sees:

- `active_tx.status = committed`,
- `active_tx.phase = committed`,
- `active_tx.next_action = tx.end.done`,

and correctly treats the transaction as still active.

The system then behaves as designed at the transaction layer, but the agent-level workflow contract remains too easy to misread.

## Root cause

The root cause is a contract misalignment between:

1. the canonical workflow expressed in `.rules`,
2. the generated `.rules` delivered by `zed-agentops-init.sh`,
3. and the response payloads of workflow-driving tools such as:
   - `commit_if_verified`
   - `repo_commit`
   - `repo_verify`

More specifically:

- the rules define a multi-step lifecycle with `committed` and `done` as separate states,
- the tools implement that separation,
- but the tool responses do not expose the separation clearly enough for agents to act on it reliably.

This leaves too much interpretation to the caller.

## Goal

For 0.5.2, make the workflow contract around verify/commit/finalize explicit and machine-actionable.

The system should make it unambiguous that:

- commit success does not necessarily mean terminal task completion,
- `committed` is a meaningful non-terminal state,
- terminal success requires `tx.end.done`,
- and agents must use the reported canonical next action to decide whether follow-up work is still required.

## Desired outcome

After 0.5.2:

- `.rules` should explicitly tell agents how to interpret successful commit helpers,
- `zed-agentops-init.sh` should continue to write rules that match that canonical contract,
- and tool responses should expose enough canonical state for agents to determine whether they must still call `ops_end_task`.

In particular, an agent that follows `.rules` and pays attention to tool responses should not mistakenly assume that a successful `commit_if_verified` call means the transaction is already terminal.

## Scope

### In scope

- clarifying the workflow contract in canonical `.rules`,
- ensuring bootstrap-generated `.rules` reflects the same clarified contract,
- improving the response shape of commit/verify tools so agents can infer the required next action,
- validating consistency between transaction state, rules wording, and tool outputs.

### Out of scope

- redesigning the entire transaction state machine,
- collapsing `committed` and `done` into one status,
- replacing `ops_end_task` with a different lifecycle mechanism,
- changing the semantics of terminal states,
- relying on README as the primary agent-facing contract.

## Canonical workflow clarification needed

The existing work loop already implies the right high-level ordering:

1. verify
2. committed
3. done

But for agents, the following points need to be stated much more explicitly.

### 1. `committed` is non-terminal

A successful commit helper may leave the active transaction in:

- `status = committed`
- `phase = committed`
- `next_action = tx.end.done`

That state is not terminal.

Agents must treat it as an active transaction that still requires closure.

### 2. Commit helpers do not imply terminal completion

`commit_if_verified` and `repo_commit` should be treated as commit helpers, not terminal outcome helpers.

If they succeed and the transaction remains non-terminal, the next action must still be executed.

### 3. `ops_end_task` is the terminal transition tool

The explicit terminal close must remain:

- `ops_end_task(..., status="done")` for success
- `ops_end_task(..., status="blocked")` for blocked termination

If the workflow contract keeps `committed` and `done` as distinct states, then the rules must tell agents exactly when and why `ops_end_task` is mandatory after commit.

### 4. Tool responses must surface canonical next action

Tools that advance workflow state should return machine-usable guidance, not just operation-local success data.

At minimum, a successful commit-oriented response should make it easy to infer:

- current transaction status,
- current transaction phase,
- whether the transaction is terminal,
- the canonical next action,
- whether a follow-up terminal lifecycle call is required.

## Proposed 0.5.2 contract changes

## A. Clarify `.rules`

The work loop should be expanded to explicitly state something like:

- successful commit helpers may advance the transaction only to `committed`,
- `committed` is not terminal,
- if `next_action` is `tx.end.done`, the agent must close the transaction with `ops_end_task(status="done")`,
- a transaction remains active until `status` is `done` or `blocked`.

The tooling section should also state that:

- `commit_if_verified` and `repo_commit` do not themselves guarantee terminal completion,
- agents must use returned canonical workflow fields and/or current transaction state to determine whether `ops_end_task` is still required.

## B. Keep generated `.rules` synchronized

Because initialized workspaces depend on `zed-agentops-init.sh`, any `.rules` clarification must flow through the same canonical generation path used for bootstrap.

This means the change is not limited to repository `.rules` text. It must also be reflected in:

- `workflow_rules.py`
- any fallback rules artifact
- the generated workspace `.rules` content produced by `zed-agentops-init.sh`

Version 0.5.1 already established a more reliable bootstrap path. Version 0.5.2 should build on that and ensure the generated rules remain contract-identical in this area.

## C. Expand tool response contracts

The following tools should be reviewed and likely adjusted:

### `commit_if_verified`
Current behavior is operationally useful but response payload is too narrow.

The response should likely include fields such as:

- `ok`
- `sha`
- `message`
- `tx_status`
- `tx_phase`
- `next_action`
- `terminal`
- `requires_followup`
- optionally `followup_tool`

The key point is not the exact field names, but that the response must make the post-commit non-terminal state obvious.

### `repo_commit`
This tool should return the same workflow-level cues as `commit_if_verified`, including whether the transaction remains active and what the next required action is.

### `repo_verify`
This tool may also benefit from returning canonical workflow cues such as:

- `tx_status = verified`
- `next_action = tx.commit.start`

so that agents can consistently reason about multi-step progress from tool results alone.

## D. Preserve the two-stage completion model

This draft does not propose changing the transaction model so that commit automatically implies terminal success.

The current distinction between:

- `committed`
- `done`

is meaningful and should be preserved unless there is a deliberate future redesign.

The 0.5.2 objective is to make that distinction explicit and safely actionable for agents.

## Impact analysis

## 1. `.rules`
Directly affected.

The canonical rules must be revised so that agents are explicitly instructed how to handle commit success and follow-up terminal completion.

## 2. `workflow_rules.py`
Directly affected.

It is the current canonical generator for rules text and must be updated alongside `.rules` semantics.

## 3. `workflow_rules_fallback.txt`
Directly affected.

The fallback rules text must remain aligned with the canonical rules content.

## 4. `zed-agentops-init.sh`
Indirectly but materially affected.

The script is not changing because of path resolution this time, but because it is part of the rule distribution path. Any updated rules contract must be what this script ultimately writes into initialized workspaces.

## 5. `commit_manager.py`
Directly affected if response contracts are changed.

The implementation may remain behaviorally similar while returning richer workflow state.

## 6. `repo_tools.py`
Directly affected if `repo_verify` response shape is expanded and if consistency across workflow-driving tools is enforced.

## 7. tests
Directly affected.

Existing tests likely validate that commit helpers leave the transaction in `committed` with `next_action = tx.end.done`. Those expectations are still valid.

What needs to be added is coverage for:

- richer response fields,
- explicit follow-up requirements,
- consistency between response payloads and canonical tx state,
- synchronized rule text across canonical and generated forms.

## Key design decision

The most important design choice for 0.5.2 is this:

> The fix should make the existing two-stage lifecycle machine clearer to agents, rather than collapsing the lifecycle machine to fit ambiguous tool responses.

That means:

- do not hide `committed`,
- do not pretend commit is terminal if it is not,
- do not rely on human-oriented docs for agent behavior,
- do expose machine-readable next-step guidance where the workflow depends on it.

## Acceptance criteria

The 0.5.2 work should satisfy all of the following.

### Rules clarity
- The canonical `.rules` explicitly states that successful commit helpers may leave the transaction in non-terminal `committed`.
- The rules explicitly state that terminal success still requires `tx.end.done`, typically via `ops_end_task(status="done")`.
- The rules explicitly instruct agents to use canonical next action and transaction status when deciding follow-up actions.

### Bootstrap consistency
- The rules content generated into workspaces by `zed-agentops-init.sh` matches the clarified canonical contract.
- The fallback rules artifact remains synchronized with the canonical rules content.

### Tool response clarity
- `commit_if_verified` and `repo_commit` responses make it clear whether the transaction is terminal.
- Those responses include canonical workflow guidance sufficient for an agent to know whether follow-up completion is required.
- If `repo_verify` is adjusted, its response also clearly signals the next workflow step.

### Transaction consistency
- A successful commit helper that does not emit `tx.end.done` continues to leave the transaction in `committed`, not `done`.
- Tool responses do not contradict the canonical transaction state stored in `tx_state`.

### Regression safety
- Tests verify that rules text, generated rules, and tool responses stay aligned on this workflow contract.
- Tests fail if commit helpers again return success without exposing the remaining required terminal action.

## Risks

### Medium contract risk
Changing tool response shapes can affect callers that currently expect minimal payloads.

This is mitigated by:
- adding fields rather than removing existing ones,
- preserving existing success indicators,
- and keeping behavior backward-compatible where possible.

### Low workflow risk
Clarifying `.rules` should reduce ambiguity rather than introduce new behavior.

### Medium synchronization risk
Because the change spans canonical rules, generated rules, fallback rules, and tool responses, silent drift is possible unless tested explicitly.

## Expected outcome

After 0.5.2:

- agents that follow `.rules` will understand that commit success may still require explicit terminal closure,
- generated workspace rules will communicate the same contract,
- commit and verify tool responses will expose canonical workflow state strongly enough to guide the next action,
- and resumability behavior will remain strict without being surprising.

## Summary

Version 0.5.2 should resolve a workflow-contract ambiguity by aligning:

- canonical `.rules`,
- bootstrap-generated rules,
- and tool response payloads

around the fact that commit success may advance a transaction to `committed` without making it terminal.

The goal is not to change the transaction model, but to make the model explicit and machine-actionable so an agent following `.rules` and tool responses can reliably complete the workflow without leaving an unintended active transaction behind.