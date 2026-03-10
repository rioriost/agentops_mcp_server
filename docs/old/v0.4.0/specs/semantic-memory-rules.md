# Semantic Memory Rules (0.4.0)

This document specifies how semantic memory is captured, updated, and persisted for deterministic resume.

## 1) Goals
- Preserve a concise, durable summary of intent and progress.
- Interpret resume prompts (e.g., “continue”) deterministically.
- Ensure semantic memory is derived from canonical artifacts only.

## 2) Canonical Fields
- `semantic_summary` (string, required for non-terminal tx)
- `user_intent` (string, optional)

See `schema/materialized_state.md` for the canonical state schema.

## 3) Update Triggers

### 3.1 `semantic_summary`
Update on the following events:
- `tx.step.enter`
- `tx.file_intent.add|update|complete`
- `tx.verify.pass|fail`
- `tx.commit.done|fail`
- `tx.end.*`

### 3.2 `user_intent`
Update only when the user supplies explicit resume intent, such as:
- “continue”
- “resume”
- “proceed with the current ticket”

The latest explicit intent **overwrites** previous values.

## 4) Content Requirements

### 4.1 `semantic_summary` content
- 1–2 short sentences.
- Must be derived from:
  - current step
  - file intents and their states
  - verification/commit outcomes
- Must avoid transient chat context.

### 4.2 `user_intent` content
- Must reflect the **latest explicit** user instruction about resuming.
- Must not be inferred or guessed.

## 5) Persistence Guarantees
- `semantic_summary` and `user_intent` must be written **before** deriving `next_action`.
- Persistence must follow canonical writer ordering:
  `event append → state update → cursor persist`.

## 6) Validation Rules
- `semantic_summary` must be non-empty for any non-terminal transaction.
- `user_intent`, if present, must match the latest explicit user intent.
- Semantic memory must be consistent with `active_tx` status and file-intent states.

## 7) Examples

### Example summary
- “Updated recovery algorithm docs; ready to verify.”

### Example user intent
- “continue”

## 8) Alignment
- `schema/materialized_state.md`
- `architecture/recovery-algorithm.md`
- `specs/writer-pipeline.md`
