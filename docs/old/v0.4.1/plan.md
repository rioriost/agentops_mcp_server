# Implementation Plan: 0.4.1 Remove workspace_root + PATH guidance

## 0.4.1 Positioning
- This release removes `workspace_root` usage.
- Aligns MCP server behavior with Zed’s ContextServerStore working directory semantics.
- Documentation update to guide PATH for Homebrew-installed binaries.

## Objectives
- Remove `workspace_root` from `.rules` and all runtime code paths.
- Update README settings to include explicit PATH.
- Maintain test coverage >= 90%.

## Scope

### In scope
- `.rules` cleanup: remove `workspace_root` references.
- `src/` changes: delete any `workspace_root` handling, parameters, defaults, or fallbacks.
- README updates (English/Japanese): `setting.json` example with PATH.
- Tests updated to reflect removal and ensure coverage.

### Out of scope
- Any unrelated feature changes.
- Backward compatibility for `workspace_root` config.

---

## 1) Problem Statement (Normalized)
- Zed passes the project root as the working directory for MCP servers, making `workspace_root` redundant.
- Zed launches shells in non-interactive mode; only `.zshenv` is loaded, so Homebrew paths from `.zprofile` are missing.
- Current docs imply `workspace_root` usage and omit PATH guidance, leading to runtime failures when binaries are not found.

---

## 2) Design Principles (0.4.1)
1. **Rely on host-provided working directory**
   - Do not override or re-resolve workspace roots.
2. **Minimal surface change**
   - Remove only what’s redundant; avoid unrelated refactors.
3. **Clear operational guidance**
   - Document PATH explicitly for Homebrew installations.
4. **Coverage preservation**
   - Maintain >= 90% test coverage.

---

## 3) Target Changes

### 3.1 `.rules` updates
- Remove `workspace_root` usage or mention.
- Keep any remaining required instructions intact.

### 3.2 Runtime changes (`src/`)
- Delete any `workspace_root` parameters in constructors, config models, or CLI parsing.
- Remove any path resolution that uses `workspace_root`.
- Ensure the working directory is taken from the host process environment only.

### 3.3 Documentation changes
- Update README setting snippet to:

```/dev/null/setting.json#L1-9
{
  "agentops-server": {
    "command": "/opt/homebrew/bin/agentops_mcp_server",
    "args": [],
    "env": {
      "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
  }
}
```

- Apply in both `README.md` and `README-jp.md` if present.

### 3.4 Tests and coverage
- Remove tests that assert `workspace_root` is required or propagated.
- Add/adjust tests to confirm:
  - No `workspace_root` in configuration.
  - Defaults still function using host working directory.
- Ensure overall coverage remains >= 90%.

---

## 4) Phases & Tasks

### Phase 1: Plan & doc alignment
- **p1-t1**: Define removal scope and identify all `workspace_root` references.
- **p1-t2**: Draft doc updates for README settings snippet.

### Phase 2: Implementation
- **p2-t1**: Remove `workspace_root` from `.rules`.
- **p2-t2**: Remove `workspace_root` from config schema and runtime code.
- **p2-t3**: Update README files with PATH guidance.

### Phase 3: Tests
- **p3-t1**: Update unit/integration tests to match new config.
- **p3-t2**: Verify coverage remains >= 90%.

### Phase 4: Verification & Release
- **p4-t1**: Run verification suite.
- **p4-t2**: Confirm acceptance criteria.

---

## 5) Acceptance Criteria
- `.rules` no longer contains `workspace_root`.
- No references to `workspace_root` exist in `src/` or configuration schema.
- README(s) include the specified `setting.json` with PATH.
- Test coverage >= 90% and tests pass.

---

## 6) Risks & Mitigations
- **Risk:** Hidden dependency on `workspace_root` in edge flows.
  - **Mitigation:** Search codebase for references and remove all usages; update tests to catch regressions.
- **Risk:** PATH guidance becomes outdated for non-Homebrew setups.
  - **Mitigation:** Keep guidance scoped to Homebrew example only.

---

## 7) Deliverables
- `docs/v0.4.1/plan.md`
- `docs/v0.4.1/tickets_list.json`
- `docs/v0.4.1/pX-tY.json` tickets
- Updated `.rules`, `README.md`, `README-jp.md`, and any affected `src/` and test files.