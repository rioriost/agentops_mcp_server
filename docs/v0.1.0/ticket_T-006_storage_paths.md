# T-006 Per-project storage paths and locking strategy

## Goal
Define where `journal.jsonl`, `snapshot.json`, and `checkpoint.json` live per project and how to lock access safely for concurrent writes.

## Requirements (from v0.1.0 plan)
- Files are **per project root** (one MCP server per project).
- `journal.jsonl` is append-only with monotonic `seq`.
- `snapshot.json` is a state snapshot.
- `checkpoint.json` records the roll-forward start point.

---

## Storage layout (per project root)

All files live under the project’s `.agent/` directory to keep state co-located with the repo:

```
<project_root>/
  .agent/
    journal.jsonl
    snapshot.json
    checkpoint.json
```

**Rationale**
- Keeps state alongside project for portability.
- Mirrors existing `.agent/*` usage and is consistent with prior scaffolding.
- Simplifies cleanup and initialization.

---

## File semantics

### 1) `journal.jsonl`
- Append-only, one JSON record per line.
- Each record includes `seq`, `event_id`, `ts`, `project_root`, `kind`, `payload` plus optional `session_id`, `agent_id`.

### 2) `snapshot.json`
- Single JSON document.
- Overwritten on each snapshot save.
- Contains `snapshot_id`, `ts`, `project_root`, `last_applied_seq`, `state`.

### 3) `checkpoint.json`
- Single JSON document.
- Overwritten on each checkpoint update.
- Contains `checkpoint_id`, `ts`, `project_root`, `last_applied_seq`, `snapshot_path`.

---

## Locking strategy

### Principles
- **Single-writer** per project process is assumed (MCP server per project).
- Use file locks to guard writes to avoid race conditions from parallel tool calls in the same process.

### Lock granularity
- **Journal**: lock around append + seq increment.
- **Snapshot**: lock around overwrite.
- **Checkpoint**: lock around overwrite.

### Lock mechanism
- Prefer OS-level file locking via `fcntl` (Unix) or `msvcrt` (Windows) if cross-platform support is needed.
- If cross-platform support is not required in v0.1.0, a simple **advisory lock file** is acceptable:
  - `.agent/locks/journal.lock`
  - `.agent/locks/snapshot.lock`
  - `.agent/locks/checkpoint.lock`

### Recommended approach (v0.1.0)
- **Advisory lock files** with atomic create (`O_EXCL`) to avoid adding dependencies.
- Lock lifecycle:
  1. Attempt to create lock file.
  2. If exists, retry with short backoff (e.g., 25–50ms).
  3. On success, perform write.
  4. Delete lock file.

### Failure handling
- If lock cannot be acquired within a bounded retry window (e.g., 1–2 seconds):
  - Return `{ "ok": false, "reason": "lock_timeout" }`.
  - Do not perform partial writes.

---

## Initialization expectations
- `.agent/` is created if missing.
- `journal.jsonl` may be created lazily on first append.
- `snapshot.json` and `checkpoint.json` are created on first write.

---

## Notes for later tickets
- T-007+ event hooks should call `journal.jsonl` append and must respect locking.
- T-010 roll-forward should read without exclusive locks but should tolerate partially written lines (ignore invalid JSON line).

---

## Proposed acceptance criteria
- Documented storage layout and lock rules (this file).
- Implementation can safely append to journal and overwrite snapshot/checkpoint without races.
- No external dependencies required for locks in v0.1.0.