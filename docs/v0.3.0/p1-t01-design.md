# p1-t01 Design Notes: Class Boundary Proposal for `main.py`

## Goal
Refactor `main.py` into class-based components while keeping external behavior identical to 0.2.3. Tool schemas, JSON-RPC request/response shapes, and stdout/stderr behavior must not change.

## Responsibility Map (current main.py)
- **Process/IO**: JSON-RPC stdio loop, request parsing, response writing.
- **Tool routing**: tool registry, alias mapping, workspace root handling.
- **State artifacts**: journal, snapshot, checkpoint, handoff, observability files.
- **State rebuild/replay**: journal replay, state updates, warnings.
- **Verification & git**: verify execution, git status/commit helpers.
- **Test suggestions**: test target inference from diff and failures.

## Proposed Classes

### `RepoContext`
**Responsibility**: repository paths and root resolution.
- Owns `REPO_ROOT`, artifact paths, and verify script path.
- Handles workspace root changes and restoration.
- Provides path helpers (agent dir paths).

### `StateStore`
**Responsibility**: persistence layer for journal/snapshot/checkpoint/handoff/observability.
- Read/write JSON and text artifacts.
- Journal append and sequence management.
- Snapshot/checkpoint read/write.

### `StateRebuilder`
**Responsibility**: reconstruct state from snapshot and journal.
- Replay logic, target session selection, applied event tracking.
- State mutation based on event kinds.
- Journal rotation logic (week-based).

### `GitRepo`
**Responsibility**: git command execution and diff/status helpers.
- Wraps `git` subprocess calls.
- Exposes status, diff stats, file lists.

### `VerifyRunner`
**Responsibility**: run verification script and report results.
- Executes `.zed/scripts/verify` with timeout.
- Journals verify start/end events.

### `CommitManager`
**Responsibility**: commit flows using `GitRepo`, `VerifyRunner`, `StateStore`.
- Commit if verified and repo commit with options.
- Normalization of commit messages.
- Post-commit snapshot/checkpoint rotation.

### `ToolRouter`
**Responsibility**: tool registry, alias mapping, and call dispatch.
- Owns tool schema definitions and handler binding.
- Handles workspace root switching.
- Applies truncate limits and result summarization.

### `JsonRpcServer`
**Responsibility**: request parsing and method dispatch.
- Handles `initialize`, `tools/list`, `tools/call`, shutdown/exit.
- Delegates to `ToolRouter` for tool calls.

## Module-Level API
Keep current module-level functions as thin wrappers that delegate to class instances. This preserves public import paths and test expectations.

## Migration Steps (incremental)
1. Introduce `RepoContext` + `StateStore` to encapsulate artifact paths and IO.
2. Move replay logic into `StateRebuilder`.
3. Extract `GitRepo` + `VerifyRunner`.
4. Add `CommitManager` and redirect commit flows.
5. Add `ToolRouter` and refactor `tools_list`/`tools_call`.
6. Add `JsonRpcServer` and refactor `handle_request`/`main`.

## Risk Areas / Guardrails
- Tool schema definitions must stay identical.
- JSON-RPC responses must preserve formatting and error handling.
- Logging/journal event kinds and payloads must remain stable.
- Workspace root switching must restore previous root correctly.

## Behavior Parity Notes
- Keep all public tool function names unchanged.
- Preserve exception messages and error codes.
- Maintain stdout output ordering in `main()` loop.