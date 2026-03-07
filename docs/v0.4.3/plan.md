# Implementation Plan: 0.4.3 fix path resolution

## 0.4.3 Positioning
- Ensure MCP server tools resolve paths relative to CWD.
- Centralize path resolution logic in one place.
- Prevent running with CWD set to `/`.

## Objectives
- Enforce CWD validation on MCP server startup.
- Consolidate all tool path expansion through a single resolver.
- Maintain test coverage >= 90%.

## Scope

### In scope
- Startup CWD validation and error handling.
- Unification of path resolution logic used by tools.
- Tests to cover path resolution and startup validation.

### Out of scope
- Large refactors unrelated to path resolution.
- New tool features.

---

## 1) Problem Statement (Normalized)
- Tools may expand paths incorrectly (e.g., `/.agent` instead of `<cwd>/.agent`), leading to read-only filesystem errors (e.g., `ops_capture_state` and `ops_handoff_export`).
- Path expansion logic might be duplicated across the codebase.
- Server allows startup with CWD `/`, which should be rejected (even if normal Zed launch uses the project directory).

---

## 2) Design Principles (0.4.3)
1. **Single source of truth for paths**
   - All tool-related paths must go through one resolver.
2. **Fail fast**
   - Reject startup when CWD is `/`.
3. **Minimal safe change**
   - Adjust only what’s required to fix resolution behavior.
4. **Coverage preservation**
   - Keep test coverage >= 90%.

---

## 3) Target Changes

### 3.1 Centralize path resolution
- Locate all path expansion logic in `src/` and route it through a single helper.
- Ensure helper expands paths relative to CWD.

### 3.2 Startup CWD validation
- On MCP server startup, check CWD.
- If CWD is `/`, return a clear error and abort initialization.

### 3.3 Tests and coverage
- Add/adjust tests for:
  - path expansion uses CWD
  - CWD `/` is rejected
- Maintain coverage >= 90%.

---

## 4) Phases & Tasks

### Phase 1: Analysis & Planning
- **p1-t1**: Identify all path resolution usages in `src/` and the existing resolver(s).
- **p1-t2**: Draft plan for consolidation and startup validation.

### Phase 2: Implementation
- **p2-t1**: Implement single path resolver and migrate all call sites.
- **p2-t2**: Add startup CWD validation with clear error message.

### Phase 3: Tests
- **p3-t1**: Add/update tests for path resolution and CWD validation.
- **p3-t2**: Validate coverage remains >= 90%.

### Phase 4: Verification & Release
- **p4-t1**: Run verification suite.
- **p4-t2**: Confirm acceptance criteria.

---

## 5) Acceptance Criteria
- All tool path expansions resolve relative to CWD.
- Startup fails with a clear error when CWD is `/`.
- Test coverage >= 90% and tests pass.

---

## 6) Risks & Mitigations
- **Risk:** Hidden path expansion in less obvious utility code.
  - **Mitigation:** Use project-wide search and tests to confirm single resolver usage.
- **Risk:** Error handling change affects tool startup flows.
  - **Mitigation:** Keep error message explicit; add tests for startup failure case.

---

## 7) Deliverables
- `docs/v0.4.3/plan.md`
- `docs/v0.4.3/tickets_list.json`
- `docs/v0.4.3/pX-tY.json` tickets
- Source changes in `src/` for path resolution and startup validation
- Tests updated/added