# Transaction Event Taxonomy (0.4.0)

This document defines the **transaction event taxonomy** used by 0.4.0 for deterministic resume.

## 1) Record Envelope (Required Fields)

Every event record MUST include:

- `seq`: monotonic integer sequence (append-only)
- `ts`: RFC 3339 timestamp (UTC)
- `tx_id`: transaction identifier (string, stable per ticket run)
- `ticket_id`: ticket identifier (string)
- `event_type`: string event name (see taxonomy below)
- `phase`: lifecycle phase (`planned|in-progress|checking|verified|committed|done|blocked`)
- `step_id`: step identifier (string; required for `tx.step.enter` and step-scoped events; use a sentinel like `none` for boundary-only events such as `tx.begin` and `tx.end.*`)
- `actor`: object describing the source of the event
- `session_id`: session identifier (string)
- `payload`: event-specific object (see definitions)

### Actor (recommended fields)
- `agent_id`: identifier for the agent/runtime
- `tool`: tool or subsystem name (e.g., `ops_tools`, `commit_manager`)
- `role`: optional role label (e.g., `system`, `assistant`)

## 2) Event Types

### 2.1 Transaction Boundaries

- **`tx.begin`**
  - Purpose: Begin a new transaction for a ticket.
  - Required payload:
    - `ticket_id` (string)
    - `ticket_title` (string, optional but recommended)
  - Notes: Must occur before any file intent or mutation events. Use `step_id: "none"` for boundary-only events like `tx.begin`.

- **`tx.step.enter`**
  - Purpose: Mark entry to a logical step.
  - Required payload:
    - `step_id` (string)
    - `description` (string, optional)

- **`tx.end.done`**
  - Purpose: Terminal event for completed transaction.
  - Required payload:
    - `summary` (string)
    - `next_action` (string, optional)

- **`tx.end.blocked`**
  - Purpose: Terminal event for blocked transaction.
  - Required payload:
    - `reason` (string)
    - `summary` (string, optional)
    - `next_action` (string, optional)

### 2.2 File Intent Events

All mutation-related work MUST be preceded by file intent registration.
Intent `planned_step` MUST reference a `tx.step.enter` step_id, and intent state must advance monotonically (`planned → started → applied → verified`).
`verified` state is only valid after `tx.verify.pass` for the owning step.

- **`tx.file_intent.add`**
  - Purpose: Register intent before first mutation.
  - Required payload:
    - `path` (string, repo-relative)
    - `operation` (string: `create|update|delete|move|rename`)
    - `purpose` (string, semantic intent)
    - `planned_step` (string, step_id reference)
    - `state` (string: `planned`)

- **`tx.file_intent.update`**
  - Purpose: Update intent state during execution.
  - Required payload:
    - `path` (string)
    - `state` (string: `started|applied|verified`)
    - `last_event_seq` (int, optional)

- **`tx.file_intent.complete`**
  - Purpose: Mark intent as complete.
  - Required payload:
    - `path` (string)
    - `state` (string: `verified`)
    - `last_event_seq` (int, optional)

### 2.3 Verification Events

- **`tx.verify.start`**
  - Purpose: Mark verification start.
  - Required payload:
    - `command` (string, optional)
    - `target` (string, optional)

- **`tx.verify.pass`**
  - Purpose: Verification passed.
  - Required payload:
    - `ok` (bool = true)
    - `returncode` (int, optional)
    - `summary` (string, optional)

- **`tx.verify.fail`**
  - Purpose: Verification failed.
  - Required payload:
    - `ok` (bool = false)
    - `returncode` (int, optional)
    - `error` (string, optional)
    - `summary` (string, optional)

### 2.4 Commit Events

- **`tx.commit.start`**
  - Purpose: Mark commit start.
  - Required payload:
    - `message` (string)
    - `files` (string or list, optional)

- **`tx.commit.done`**
  - Purpose: Commit finished.
  - Required payload:
    - `sha` (string, optional)
    - `summary` (string, optional)

- **`tx.commit.fail`**
  - Purpose: Commit failed.
  - Required payload:
    - `error` (string)
    - `summary` (string, optional)

## 3) Ordering Notes (Summary)

- `tx.begin` MUST precede all other tx events.
- `tx.file_intent.add` MUST precede any mutation-related activity for the same path.
- `tx.end.*` is terminal; no further events for the same `tx_id`.

Detailed ordering invariants are defined in `lifecycle_invariants.md`.