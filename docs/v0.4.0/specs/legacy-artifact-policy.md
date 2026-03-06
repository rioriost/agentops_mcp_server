# Legacy Artifact Policy (0.4.0)

This document defines how legacy persistence artifacts are removed or replaced in the 0.4.0 breaking redesign.

## 1) Goals
- Declare which legacy artifacts remain, which are removed, and which are replaced.
- Make **canonical sources of truth** explicit.
- Preserve output path policy under `CWD/.agent/`.
- Avoid any backward-compatibility guarantees.

## 2) Canonical Sources (0.4.0)
**Canonical artifacts (sources of truth):**
1. **Transaction Event Log** (append-only)
2. **Materialized Transaction State**

All resume decisions MUST be derived from these artifacts only.

## 3) Legacy Artifact Inventory (Pre-0.4.0)
- **journal**: append-only event log (legacy event semantics)
- **snapshot**: materialized state snapshot (legacy schema)
- **checkpoint**: cursor to the last applied journal entry
- **handoff**: human-readable summary for resume

## 4) Replacement Mapping (0.4.0)
| Legacy Artifact | Legacy Role | 0.4.0 Status | 0.4.0 Replacement |
| --- | --- | --- | --- |
| journal | event history | **Replaced** | Transaction Event Log |
| snapshot | materialized state | **Replaced** | Materialized Transaction State |
| checkpoint | last-applied cursor | **Replaced** | `last_applied_seq` embedded in materialized state |
| handoff | resume summary | **Derived-only** | Regenerated from canonical state |

Notes:
- `handoff` remains **optional and derived**. It is never a source of truth.
- The legacy journal/snapshot/checkpoint **schemas are removed**; no compatibility layer is provided.

## 5) Path Policy (Unchanged)
- Canonical artifacts are written under `CWD/.agent/`.
- The existing path resolution logic is reused.
- No new output root or directory structure is introduced in 0.4.0.

## 6) Read/Write Policy
- Writers MUST follow canonical ordering:
  `event append → state update → cursor persist`.
- Readers MUST ignore legacy artifacts when canonical artifacts are present.

## 7) Backward Compatibility
- 0.4.0 is a **breaking redesign**.
- **No backward compatibility** is provided for legacy artifacts or schemas.
- Any residual legacy files are ignored by resume logic.

## 8) Alignment
- `specs/writer-pipeline.md`
- `specs/rebuild-engine.md`
- `specs/semantic-memory-rules.md`
- `specs/resume_logic.md`
- `architecture/recovery-algorithm.md`
- `architecture/lifecycle_invariants.md`
