# Implementation Plan: Agent state file path unification

## Objectives
- Centralize path selection for journal, checkpoint, snapshot, and handoff files.
- Ensure all state artifacts are read/written under `<workspace_root>/.agent/`.
- Remove/ignore `path` arguments from `ops*` tools.

## Assumptions
- Existing filenames (e.g., `checkpoint.json`, `snapshot.json`, `journal.jsonl`) remain unchanged.
- State reads/writes should remain compatible, only path selection is unified.

## Phases

### Phase 1: Discovery & design
**Goals**
- Locate all path construction logic for journal/checkpoint/snapshot/handoff.
- Identify all `ops*` tool handlers that accept `path`.

**Deliverables**
- Inventory of call sites.
- Definition of a single path resolution function signature.

**Tasks**
- Search codebase for `.agent`, `checkpoint`, `snapshot`, `journal`, `handoff` path usage.
- Draft `state_path(workspace_root, artifact_kind)` API and expected filenames.

---

### Phase 2: Implementation
**Goals**
- Implement unified path resolver.
- Replace path construction in all read/write call sites.
- Remove/ignore `path` argument in `ops*` handlers.

**Deliverables**
- New path resolver used everywhere.
- Updated tool handlers.

**Tasks**
- Add `state_path(...)` helper in the shared state/util module.
- Refactor journal, checkpoint, snapshot, handoff read/write to call the helper.
- Update `ops*` tool schemas/handlers to drop or ignore `path`.

---

### Phase 3: Verification
**Goals**
- Ensure behavior remains correct and tests pass.

**Deliverables**
- Updated tests (if needed).
- Verification run.

**Tasks**
- Update tests to reflect unified `.agent/` paths.
- Run `${VERIFY_REL}` and address failures.

## Acceptance Criteria Mapping
- All state artifacts save under `<workspace_root>/.agent/`.
- Exactly one function computes these paths.
- `ops*` tools do not accept or rely on a `path` parameter.
- Tests pass with unified path logic.

## Rollout Notes
- No file format changes or migrations required.
- Keep legacy filenames intact to avoid breaking state loading.