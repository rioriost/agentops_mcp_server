# Resume Logic Specification (0.4.0)

This document defines deterministic resume logic that interprets semantic intent using persisted semantic memory. It complements the writer pipeline, semantic memory rules, and rebuild engine specifications.

## 1) Goals
- Deterministically select the correct transaction to resume.
- Derive `next_action` solely from canonical state.
- Interpret explicit user resume intent (e.g., “continue”) without relying on chat context.
- Resolve torn-state conditions with clear precedence rules.

## 2) Canonical Inputs
Resume logic MUST use only:
- **Transaction event log** (canonical history)
- **Materialized transaction state** (derived, trusted only if integrity passes)

No legacy artifacts are permitted as sources of truth in 0.4.0.

## 3) Preconditions
- Canonical artifacts are resolved under `CWD/.agent/`.
- If materialized state integrity fails, rebuild from the event log before any resume decision.

## 4) Transaction Selection (Deterministic)
### 4.1 Target Selection
- **Primary target**: latest **non-terminal** transaction.
- **Terminal** means `tx.end.done` or `tx.end.blocked` has occurred.

### 4.2 Tie-breakers
If multiple non-terminal transactions exist:
1. Prefer the transaction with the **highest valid event `seq`**.
2. If `seq` ties or corruption is detected, rebuild from log and re-evaluate.

### 4.3 No Active Transaction
If no non-terminal transaction exists:
- Resume starts a **new** transaction via `tx.begin` for the next planned ticket.

## 5) `next_action` Derivation Rules
`next_action` MUST be computed strictly from:
- `active_tx.status` / `phase`
- `current_step` / `last_completed_step`
- `verify_state` / `commit_state`
- `file_intents[]` states
- `semantic_summary` / `user_intent`

No external context may be used.

### 5.1 Status Mapping
- **planned** → `tx.begin`
- **in-progress**
  - If any `file_intents` are `planned|started` → resume file operations
  - If all intents are `applied` → `tx.verify.start`
- **checking**
  - If `verify_state == not_started` → `tx.verify.start`
  - If `verify_state == failed` → fix and re-verify
- **verified**
  - If `commit_state == not_started` → `tx.commit.start`
- **committed** → `tx.end.done`
- **blocked** → `tx.end.blocked`

### 5.2 File-Intent Guidance
- If any intent is `planned`, the next action should be to **start** that intent.
- If intents are `started` but not `applied`, the next action should be to **complete** the intent.
- If all intents are `applied`, move to verification.

## 6) Semantic Intent Interpretation
### 6.1 `user_intent`
- Only explicit user resume instructions update `user_intent` (e.g., “continue”).
- The latest explicit intent **overwrites** previous values.

### 6.2 Intent Effects
- If `user_intent` is present, it **guides** the resume path but does not override invariants.
- Example: if `user_intent == "continue"` and status is `checking` with `verify_state == failed`, the correct action is **fix and re-verify**, not to skip verification.

### 6.3 `semantic_summary`
- Must be consistent with the derived `next_action`.
- If inconsistent, rebuild from the event log and re-derive.

## 7) Precedence Rules (Materialized vs Log)
- **Event log is canonical**.
- Materialized state is trusted only if integrity checks pass **and** cursor matches the latest valid event `seq`.
- If mismatch is detected, rebuild from the event log and recompute `next_action`.

## 8) Edge Cases
### 8.1 Corrupted Tail Events
- Truncate to last valid `seq`.
- Rebuild and re-derive `next_action`.

### 8.2 Integrity Mismatch
- Discard materialized state and rebuild from log.

### 8.3 Missing File-Intent for Mutations
- Treat as invariant violation.
- Resume must not proceed until corrected (blocked or rebuild required).

## 9) Resume Boundary Event
After selecting the target transaction and `next_action`, emit:
- `tx.step.enter` for the step being resumed
- Then proceed with the derived action

## 10) Determinism Guarantees
- Same event sequence → same target transaction → same `next_action`.
- No non-deterministic inputs are permitted.

## 11) Alignment
- `specs/writer-pipeline.md`
- `specs/semantic-memory-rules.md`
- `specs/rebuild-engine.md`
- `architecture/recovery-algorithm.md`
- `architecture/lifecycle_invariants.md`
