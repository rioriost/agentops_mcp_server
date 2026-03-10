# Rebuild Engine Specification (0.4.0)

This document defines deterministic rebuild of materialized transaction state from the transaction event log.

## 1) Goals
- Deterministically rebuild materialized state from the event log.
- Preserve semantic memory (`semantic_summary`, `user_intent`) during replay.
- Resolve torn-state conditions consistently.
- Regenerate derived handoff views from canonical state.

## 2) Inputs (Canonical Sources)
- Transaction event log (append-only).
- Optional materialized state snapshot (used only if integrity checks pass).

## 3) Replay Ordering & Cursor Handling
- Events MUST be applied strictly in ascending `seq`.
- `last_applied_seq` equals the highest `seq` successfully applied.
- Replay start:
  - If a valid snapshot exists, start from `snapshot.last_applied_seq`.
  - Otherwise start at `seq = 0`.

## 4) Integrity Checks & Mismatch Handling
- Validate snapshot integrity before use:
  - `schema_version == "0.4.0"`
  - `integrity.state_hash` matches canonical serialization
  - `last_applied_seq` ≥ `integrity.rebuilt_from_seq`
- If any validation fails, discard snapshot and rebuild from log.

## 5) Corrupted Tail Truncation Policy
- If tail events are invalid or malformed:
  - Truncate to last valid `seq`.
  - Rebuild state from the truncated log.
- Duplicate `event_id` entries are ignored and recorded as `dropped_events`.

## 6) Semantic Memory Reconstruction
- `semantic_summary` is updated during replay on:
  - `tx.step.enter`
  - `tx.file_intent.add|update|complete`
  - `tx.verify.pass|fail`
  - `tx.commit.done|fail`
  - `tx.end.*`
- `user_intent` is updated only when an explicit user intent event is observed.
- If no explicit intent exists, `user_intent` remains `null`.

## 7) Derived Handoff Regeneration
- After rebuild, regenerate any derived handoff from the canonical state.
- Handoff is a convenience view; it is never a source of truth.

## 8) Determinism Guarantees
- Same event sequence → same materialized state.
- No non-deterministic data sources are allowed during replay.

## 9) Alignment
- `schema/materialized_state.md`
- `architecture/recovery-algorithm.md`
- `specs/writer-pipeline.md`
- `specs/semantic-memory-rules.md`
