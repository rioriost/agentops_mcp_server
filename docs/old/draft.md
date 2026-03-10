# Draft for 0.4.11: ticket status persistence clarification

## Background
- The current rules define a ticket status enum and a required work loop with status transitions such as:
  - `planned`
  - `in-progress`
  - `checking`
  - `verified`
  - `committed`
  - `done`
  - `blocked`
- The current rules also describe status changes during execution, for example:
  - set status to `in-progress` when work begins,
  - set status to `checking` after verification work,
  - set status to `verified`,
  - set status to `committed`,
  - set status to `done`.
- In practice, the intent is that ticket status management is mandatory.
- However, the rules are still ambiguous about where status must be persisted and synchronized.
- In particular, it is not explicit enough whether the following are mandatory:
  1. updating the per-ticket JSON file status,
  2. updating `tickets_list.json` status,
  3. keeping those ticket-document statuses aligned with runtime transaction status.

## Problem
The current wording makes ticket status management look mandatory in principle, but partially optional in persistence behavior.

This ambiguity can cause inconsistent implementations such as:
- updating runtime transaction state but not the versioned ticket files,
- updating a per-ticket JSON file but not `tickets_list.json`,
- marking a task as completed in one artifact while another still shows an earlier status,
- leaving resume and operator-facing planning artifacts out of sync.

As a result, resumability and operator trust are weakened because the versioned docs may no longer reflect actual execution state.

## Goal
- Clarify that ticket status persistence is mandatory, not optional.
- Define which artifacts must be updated when ticket status changes.
- Define how runtime status and versioned ticket-document status stay synchronized.
- Preserve the existing strict transaction model and status enum.

## Proposed changes
- Update `.rules` so it explicitly states that ticket status persistence is mandatory, not optional bookkeeping.
- Update `.rules` so it explicitly states that every ticket status change must be persisted to:
  - the per-ticket JSON file, and
  - `tickets_list.json`.
- Define that the persisted ticket-document status is the required versioned reflection of runtime execution status for the same ticket.
- Define that runtime transaction status/phase and persisted ticket-document status must stay synchronized at each ticket lifecycle transition, rather than being reconciled later.
- Define that status persistence in versioned planning artifacts is required throughout the canonical work loop, not just during planning.
- Define the required persistence timing during the work loop:
  - when a ticket enters `in-progress`,
  - when it moves to `checking`,
  - when it becomes `verified`,
  - when it becomes `committed`,
  - when it reaches `done` or `blocked`.
- Update the checked-in `.rules` file and the `.rules` template embedded in `zed-agentops-init.sh` together so both artifacts express the same ticket status persistence contract.
- Add regression tests or contract checks that lock the expected ticket status persistence behavior and keep the checked-in `.rules` file aligned with the init-script template.

## Non-goals
- Changing the ticket status enum.
- Relaxing transaction ordering rules.
- Redesigning the planning file layout.
- Introducing a separate status model for docs versus runtime.

## Goal
- Ticket status persistence and synchronization are explicitly mandatory in the rules and implementation guidance.
- The contract clearly defines which planning artifacts must be updated, when they must be updated during execution, and how they stay aligned with runtime transaction state.

## Acceptance criteria
- `.rules` explicitly states that ticket status updates must be persisted to both per-ticket JSON files and `tickets_list.json`.
- `.rules` explicitly makes ticket status persistence mandatory throughout execution, not optional bookkeeping.
- The required synchronization rule between runtime transaction status and persisted ticket-document status is documented clearly enough to avoid divergent interpretations.
- The work loop wording makes it clear that ticket status persistence must occur at each canonical lifecycle transition.
- The checked-in `.rules` file and the `.rules` template embedded in `zed-agentops-init.sh` are required to match for ticket status persistence requirements.
- Tests or verification coverage are updated as needed to prevent regression in ticket status synchronization behavior and script/rules alignment.