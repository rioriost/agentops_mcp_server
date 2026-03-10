# p1-t01 Design Notes: Full `main.py` Split (0.3.1)

## Goal
Refactor the remaining `main.py` responsibilities into classes and split them into separate modules while preserving external behavior identical to 0.2.3 (tool schemas, JSON-RPC request/response, stdout/stderr, and journaling semantics).

## Current State (0.3.0 baseline)
Already class-based:
- **`RepoContext`**: workspace root resolution and repo root switching.
- **`ToolRouter`**: tool registry/aliasing, tool invocation, journaling.
- **`JsonRpcServer`**: JSON-RPC request handling and stdio loop.

Still module-level:
- Artifact path helpers and global state (`REPO_ROOT`, `JOURNAL`, `SNAPSHOT`, etc.).
- State store functions (journal/snapshot/checkpoint IO).
- State replay/rebuild logic.
- Git/verify/commit helpers.
- Repo/test suggestion tooling.
- Ops/handoff/observability tooling.
- `TOOL_REGISTRY` and module-level wrapper functions.

## Proposed Module + Class Layout

### 1) `repo_context.py`
**Class**: `RepoContext` (existing)
**Responsibilities**
- Resolve `workspace_root` and set repo root.
- Expose repo root and artifact path helpers.

**Functions to move**
- `_state_artifact_path`
- `_set_repo_root`
- `_resolve_workspace_root` (wrapper stays in `main.py`)

---

### 2) `state_store.py`
**Class**: `StateStore`
**Responsibilities**
- Read/write journal, snapshot, checkpoint, handoff, observability.
- Sequence management and JSON/text IO.

**Functions to move**
- `_ensure_parent`, `_write_text`, `_read_json_file`
- `_read_last_json_line`, `_next_journal_seq`
- `journal_append`, `snapshot_save`, `snapshot_load`
- `checkpoint_update`, `checkpoint_read`

---

### 3) `state_rebuilder.py`
**Class**: `StateRebuilder`
**Responsibilities**
- Replay journal events into state.
- Journal rotation, time parsing, session selection.

**Functions to move**
- `_parse_iso_ts`, `_week_start_utc`, `_read_first_event_with_ts`
- `_read_journal_events`, `_read_recent_journal_events`
- `_init_replay_state`, `_select_target_session_id`
- `_append_applied_event_id`, `_apply_event_to_state`
- `replay_events_to_state`, `roll_forward_replay`, `continue_state_rebuild`
- `_rotate_journal_if_prev_week`

---

### 4) `git_repo.py`
**Class**: `GitRepo`
**Responsibilities**
- Execute git commands and return outputs.
- Provide diff/status helpers.

**Functions to move**
- `git`
- `_git_status_porcelain`, `_git_diff_stat`, `_git_diff_stat_cached`

---

### 5) `verify_runner.py`
**Class**: `VerifyRunner`
**Responsibilities**
- Run verify script with timeout.
- Journal verify start/end.

**Functions to move**
- `run_verify`

---

### 6) `commit_manager.py`
**Class**: `CommitManager`
**Dependencies**: `GitRepo`, `VerifyRunner`, `StateStore`
**Responsibilities**
- Verify-then-commit flow.
- Commit message normalization.
- Post-commit snapshot/checkpoint rotation.

**Functions to move**
- `_commit_message_from_status`
- `_normalize_commit_message`
- `_run_git_commit`
- `_auto_snapshot_checkpoint_after_commit`
- `_post_commit_snapshot_checkpoint`
- `commit_if_verified`
- `repo_commit`

---

### 7) `repo_tools.py`
**Module functions (thin wrappers)**:
- `repo_verify`, `repo_status_summary`, `repo_commit_message_suggest`
- `session_capture_context`

---

### 8) `test_suggestions.py`
**Module functions**
- `_unique_preserve_order`, `_extract_artifact_paths`
- `_is_test_path`, `_normalize_test_candidate`, `_test_candidates_for_path`
- `_parse_changed_files`, `tests_suggest`, `tests_suggest_from_failures`

---

### 9) `ops_tools.py`
**Module functions**
- `_truncate_text`, `_build_compact_context`, `_summarize_result`, `_sanitize_args`
- `ops_compact_context`, `ops_handoff_export`, `ops_resume_brief`
- `ops_start_task`, `ops_update_task`, `ops_end_task`
- `ops_capture_state`, `ops_task_summary`, `ops_observability_summary`
- `_journal_safe` (if not kept in `state_store`)

---

### 10) `tool_registry.py`
**Responsibility**
- Own `TOOL_REGISTRY` and keep tool schema definitions stable.
- Export registry for `ToolRouter`.

---

### 11) `tool_router.py`
**Class**: `ToolRouter` (existing)
**Responsibility**
- Keep alias mapping and tool invocation.
- Add `workspace_root` + `truncate_limit` at call time.

---

### 12) `json_rpc_server.py`
**Class**: `JsonRpcServer` (existing)
**Responsibility**
- JSON-RPC routing + stdio loop unchanged.

---

### 13) `main.py`
**Responsibility**
- Wire dependencies and expose module-level wrappers:
  - `tools_list`, `tools_call`, `handle_request`, `main`
- Keep wrapper function names stable to preserve imports and tests.

## Dependency Wiring (Proposed)
- `RepoContext` provides repo root and artifact paths.
- `StateStore` depends on `RepoContext`.
- `StateRebuilder` depends on `StateStore` + `RepoContext`.
- `GitRepo` depends on `RepoContext`.
- `VerifyRunner` depends on `RepoContext` + `StateStore` (journaling).
- `CommitManager` depends on `GitRepo` + `VerifyRunner` + `StateStore`.
- `ToolRegistry` binds handlers from modules/classes above.
- `ToolRouter` depends on `ToolRegistry` + `RepoContext`.
- `JsonRpcServer` depends on `ToolRouter`.

## Migration Steps (Incremental)
1. Extract `StateStore` and update journal/snapshot/checkpoint functions to methods.
2. Extract `StateRebuilder` and redirect replay/rotate functions.
3. Extract `GitRepo` and `VerifyRunner`.
4. Extract `CommitManager` and refactor commit flows.
5. Split remaining tool modules (`repo_tools`, `ops_tools`, `test_suggestions`).
6. Move `TOOL_REGISTRY` to its own module; keep `ToolRouter` intact.
7. Leave `main.py` as wiring + wrapper exports only.

## Risk Areas / Guardrails
- Tool schemas must not change (inputs/outputs).
- JSON-RPC error handling/format must match existing behavior.
- Journaling event kinds/payloads must be identical.
- Workspace root switching must restore previous root reliably.
- Keep stdout response ordering in `JsonRpcServer.run()`.

## Behavior Parity Notes
- Preserve public function names and signatures for tool handlers.
- Keep error messages and exception types stable.
- Maintain truncation logic and summary formatting.