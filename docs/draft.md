# Draft: Agent state file path unification

## Background
Currently, state artifacts (journal, checkpoint, snapshot, handoff) are written to files under the workspace root. The paths are decided in multiple places, and `ops*` tools also accept a `path` argument. This causes duplication and makes it easy to drift.

## Goal
- Centralize the path decision logic for all state artifacts.
- Ensure all state files are written under `workspace_root/.agent/`.
- Remove/ignore the `path` argument from `ops*` tools so callers cannot override.
- Keep behavior otherwise compatible.

## Scope
- Implement a single function that takes the workspace root and artifact type and returns the full file path.
- Update all code paths that write or read journal/checkpoint/snapshot/handoff to use the new function.
- Remove usage of `path` in `ops*` tool handlers (argument deprecated/ignored).

## Non-goals
- Changing file formats.
- Changing retention or naming conventions beyond centralization.
- Modifying tool schemas beyond removing/ignoring `path` in `ops*`.

## Acceptance criteria
- All state artifacts are saved under `<workspace_root>/.agent/`.
- There is exactly one function used to compute the file paths.
- `ops*` tools no longer accept or rely on a `path` parameter.
- Existing tests pass or are updated to reflect the unified path logic.

## Notes
- Ensure legacy filenames (e.g., `checkpoint.json`, `snapshot.json`, `journal.jsonl`) are preserved unless explicitly migrated.