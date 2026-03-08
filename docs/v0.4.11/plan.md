# Implementation Plan: 0.4.11 Ticket status persistence clarification

## Objectives
- Clarify that ticket status management is mandatory throughout execution, not optional bookkeeping.
- Define exactly which planning artifacts must be updated when ticket status changes.
- Define how runtime transaction status and persisted ticket-document status stay synchronized.
- Keep the checked-in `.rules` file and the `.rules` template embedded in `zed-agentops-init.sh` aligned on the same contract.

## Background
Current rules already imply a strict ticket lifecycle through the status enum and the required work loop. However, the contract is still ambiguous about persistence responsibilities.

In practice, the ambiguity appears in questions such as:
- whether updating a per-ticket JSON file is required,
- whether updating `tickets_list.json` is required,
- whether runtime status alone is sufficient,
- whether the checked-in `.rules` file and the init-script template must both be updated together.

That ambiguity weakens resumability because operators and agents may see different status values depending on which artifact they inspect.

## Problem Statement
The current wording makes ticket status progression look mandatory in principle, but partially optional in persistence behavior.

This can lead to inconsistent execution patterns such as:
1. runtime transaction state advancing while versioned ticket files remain stale,
2. per-ticket JSON files being updated without updating `tickets_list.json`,
3. ticket-document status and runtime transaction status drifting apart,
4. checked-in `.rules` and the init-script template diverging over time.

The release should remove that ambiguity and make the persistence contract explicit.

## Scope

### In scope
- Clarify mandatory persistence of ticket status changes
- Clarify synchronization expectations between runtime transaction state and versioned ticket artifacts
- Update the checked-in `.rules` file
- Update the `.rules` template embedded in `zed-agentops-init.sh`
- Add regression coverage or contract checks for rules/template alignment and ticket-status persistence expectations

### Out of scope
- Changing the ticket status enum
- Relaxing transaction ordering rules
- Redesigning the docs layout under `docs/__version__/`
- Introducing a separate docs-only status model independent from runtime state

## Phases

### Phase 1: Define the ticket status persistence contract
**Goals**
- Define the normative contract for ticket status persistence.
- Remove ambiguity about which artifacts must be updated and when.

**Tasks**
- Define that ticket status persistence is mandatory, not optional.
- Define that status changes must be reflected in:
  - the per-ticket JSON file, and
  - `tickets_list.json`.
- Define the relationship between runtime transaction status/phase and persisted ticket-document status.
- Define when status persistence must occur during the canonical work loop.
- Define that the checked-in `.rules` file and the init-script `.rules` template must remain aligned.

**Deliverables**
- Clear contract for mandatory ticket status persistence
- Clear contract for runtime-to-ticket status synchronization
- Clear contract for checked-in rules and init-template alignment

---

### Phase 2: Rules and scaffold alignment
**Goals**
- Make the mandatory persistence contract explicit in the checked-in rules.
- Ensure newly initialized projects receive the same contract.

**Tasks**
- Update `.rules` so it explicitly states:
  - ticket status persistence is mandatory,
  - status updates must be persisted to both per-ticket JSON files and `tickets_list.json`,
  - persistence occurs throughout the work loop, not just during planning.
- Update the `.rules` heredoc in `src/agentops_mcp_server/zed-agentops-init.sh` to match the checked-in `.rules` content for the relevant sections.
- Clarify status synchronization language so runtime and planning artifacts cannot drift by interpretation alone.

**Deliverables**
- Updated checked-in `.rules`
- Updated `zed-agentops-init.sh` rules template
- Matching ticket-status persistence language in both places

---

### Phase 3: Verification and regression protection
**Goals**
- Prevent future drift between rules and scaffolded rules.
- Lock the persistence contract with tests or equivalent checks.

**Tasks**
- Add or extend tests that verify:
  - the checked-in `.rules` file includes mandatory ticket-status persistence language,
  - the init-script `.rules` template includes matching language,
  - the required persistence destinations are explicitly documented,
  - synchronization expectations are described consistently enough to prevent regression.
- Run repository verification and any targeted tests relevant to rules/template alignment.

**Deliverables**
- Regression checks for ticket-status persistence contract
- Regression checks for `.rules` and init-template alignment
- Verification evidence for the release

## Acceptance Criteria
- `.rules` explicitly states that ticket status updates must be persisted to both per-ticket JSON files and `tickets_list.json`.
- `.rules` explicitly makes ticket status management mandatory throughout execution.
- The `.rules` template embedded in `zed-agentops-init.sh` matches the checked-in `.rules` content for ticket-status persistence requirements.
- The relationship between runtime transaction status and persisted ticket-document status is documented clearly enough to avoid divergent interpretations.
- Tests or verification checks protect against regression in ticket-status persistence wording and script/rules alignment.

## Risks and Mitigations
- **Risk:** The wording may still leave room for interpretation about synchronization timing.  
  **Mitigation:** Make the work-loop persistence points explicit and tie them to status transitions.

- **Risk:** The checked-in `.rules` file and the init-script template may drift again later.  
  **Mitigation:** Add tests or contract checks that assert the required language appears in both places.

- **Risk:** The release may overreach into runtime implementation changes unnecessarily.  
  **Mitigation:** Keep `0.4.11` focused on contract clarity, rules alignment, and regression protection unless a minimal implementation adjustment is proven necessary.

## Verification Strategy
- Run repository verification.
- Run targeted tests for rules/template alignment.
- Confirm that the required persistence targets are explicitly stated in both the checked-in `.rules` file and the init-script template.
- Confirm that the final wording consistently treats ticket status persistence as mandatory.

## Rollout Notes
- Keep the release small and contract-focused.
- Prefer explicit wording over inferred intent.
- Treat scaffold alignment as mandatory so newly initialized projects receive the same rules contract as the repository itself.