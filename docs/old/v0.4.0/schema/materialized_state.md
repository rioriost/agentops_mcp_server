# Materialized Transaction State Schema (0.4.0)

This document defines the **canonical materialized transaction state** for deterministic resume in 0.4.0.

## 1) Overview

The materialized state is a projection of the transaction event log. It is optimized for:
- fast resume decisions (`next_action`)
- integrity validation (`state_hash`, `rebuilt_from_seq`)
- deterministic replay (`last_applied_seq`)

**Canonical truth** remains the event log. Materialized state is authoritative **only if integrity checks pass**.

---

## 2) Top-Level Schema

```json
{
  "schema_version": "0.4.0",
  "active_tx": { ... },
  "last_applied_seq": 0,
  "integrity": {
    "state_hash": "...",
    "rebuilt_from_seq": 0
  },
  "updated_at": "2026-01-01T00:00:00Z"
}
```

### Field Definitions

- `schema_version` (string, required)  
  - Must be `"0.4.0"` for this release.
- `active_tx` (object, required)  
  - The latest **non-terminal** transaction state.
- `last_applied_seq` (int, required)  
  - Highest event `seq` applied to this state.
- `integrity` (object, required)  
  - `state_hash` (string, required): hash of the canonical state payload.  
  - `rebuilt_from_seq` (int, required): highest `seq` used when state was rebuilt.
- `updated_at` (string, required)  
  - RFC 3339 timestamp (UTC).

---

## 3) `active_tx` Schema

```json
{
  "tx_id": "tx-123",
  "ticket_id": "p3-t1",
  "status": "in-progress",
  "phase": "in-progress",
  "current_step": "p3-t1-s2",
  "last_completed_step": "p3-t1-s1",
  "next_action": "apply changes to state_store",
  "semantic_summary": "Added tx schema docs and invariants",
  "user_intent": "continue",
  "verify_state": {
    "status": "not_started",
    "last_result": null
  },
  "commit_state": {
    "status": "not_started",
    "last_result": null
  },
  "file_intents": [
    {
      "path": "src/agentops_mcp_server/state_store.py",
      "operation": "update",
      "purpose": "add tx event schema and materialized state persistence",
      "planned_step": "p3-t1-s2",
      "state": "planned",
      "last_event_seq": 210
    }
  ]
}
```

### Field Definitions

- `tx_id` (string, required)  
  - Unique transaction identifier for a single ticket execution.
- `ticket_id` (string, required)  
  - Ticket identifier (e.g., `p1-t2`).
- `status` (string, required)  
  - Must be one of:  
    `planned | in-progress | checking | verified | committed | done | blocked`
- `phase` (string, required)  
  - Current lifecycle phase (same enum as `status`).
- `current_step` (string, required)  
  - Active step identifier.
- `last_completed_step` (string, optional)  
  - Last successfully completed step.
- `next_action` (string, required)  
  - Deterministic next action for resume.
- `semantic_summary` (string, required)  
  - Concise semantic summary of current progress and intent.
- `user_intent` (string, optional)  
  - Latest user resume intent (e.g., “continue”).
- `verify_state` (object, required)
  - `status`: `not_started | running | passed | failed`
  - `last_result`: optional structured result (command, returncode, summary)
- `commit_state` (object, required)
  - `status`: `not_started | running | passed | failed`
  - `last_result`: optional structured result (sha, summary, error)
- `file_intents` (array, required)  
  - See Section 4.

---

## 3.1) Semantic Memory Update Semantics

- `semantic_summary` is updated on:
  - `tx.step.enter`
  - `tx.file_intent.add|update|complete`
  - `tx.verify.pass|fail`
  - `tx.commit.done|fail`
  - `tx.end.*`
- `user_intent` is updated only when a user provides explicit resume intent (e.g., “continue”).
- `user_intent` persists until replaced by a newer explicit intent.
- Both fields must be persisted before any resume decision is derived.

## 4) `file_intents[]` Schema

```json
{
  "path": "path/to/file",
  "operation": "create|update|delete|move|rename",
  "purpose": "why this file is being changed",
  "planned_step": "step-id",
  "state": "planned|started|applied|verified",
  "last_event_seq": 123
}
```

### Field Definitions

- `path` (string, required)  
  - Repo-relative target path.
- `operation` (string, required)  
  - One of: `create | update | delete | move | rename`
- `purpose` (string, required)  
  - Semantic intent (human-readable).
- `planned_step` (string, required)  
  - The step associated with this intent.
- `state` (string, required)  
  - One of: `planned | started | applied | verified`
- `last_event_seq` (int, optional)  
  - Most recent event seq touching this intent.

---

## 5) Integrity Model

- `state_hash` is computed over a **canonical serialization** of the state:
  - stable key ordering
  - no transient fields (e.g., runtime-only)
- `rebuilt_from_seq` is set when state is rebuilt from log:
  - should be equal to `last_applied_seq` at rebuild time

**Rule**: If `state_hash` validation fails, discard materialized state and rebuild from event log.

---

## 6) Validation Rules & Invariants

1. **Single active transaction**: `active_tx` must refer to the latest non-terminal tx.
2. **Intent-before-mutation**: `file_intents` must exist before any mutation events.
3. **Monotonic steps**: `last_completed_step` must not regress.
4. **Monotonic intent states**: `planned → started → applied → verified` only.
5. **Status/phase consistency**: `phase` must align with `status`.
6. **Semantic memory required**: `semantic_summary` must be non-empty for any non-terminal status.
7. **User intent provenance**: if `user_intent` is present, it must reflect the latest explicit user resume intent.
8. **Cursor coherence**: `last_applied_seq` must be ≥ `rebuilt_from_seq`.

---

## 7) Deterministic Resume

`next_action` is derived **only** from:
- `status` / `phase`
- `current_step` / `last_completed_step`
- `verify_state` / `commit_state`
- `file_intents` states
- `semantic_summary` / `user_intent` (for interpreting resume prompts)

The same event log sequence must always yield the same `next_action`.

---

## 8) Compatibility Notes

0.4.0 is a **breaking redesign**:
- No backward compatibility is required for prior schemas.
- Legacy artifacts are treated as **derived-only** if retained.