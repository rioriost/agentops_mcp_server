# Implementation Plan: Fix workspace_root resolution

## Objectives
- Ensure `workspace_root` resolves to the actual CWD when passed as a relative root name.
- Prevent creation of nested paths like `<cwd>/<root>/<root>/.agent`.
- Keep behavior stable for absolute `workspace_root` inputs.

## Assumptions
- CWD is the repository root when the MCP server is launched.
- Clients may pass `workspace_root` as either absolute or relative.

## Phases

### Phase 1: Discovery & design
**Goals**
- Locate `workspace_root` handling logic.
- Define resolution rules for relative inputs.

**Tasks**
- Identify where `workspace_root` is parsed and applied.
- Decide on resolution logic:
  - If relative and matches `Path.cwd().name`, use `Path.cwd()`.
  - Otherwise resolve relative to CWD.

---

### Phase 2: Implementation
**Goals**
- Apply the new resolution logic.
- Ensure state paths use the corrected root.

**Tasks**
- Update `tools_call` to use the new resolver for `workspace_root`.
- Add/adjust tests to cover relative workspace_root behavior.

---

### Phase 3: Verification
**Goals**
- Confirm `.agent` writes happen under `<cwd>/.agent`.

**Tasks**
- Run `${VERIFY_REL}` and ensure tests pass.

## Acceptance Criteria Mapping
- Relative `workspace_root` matching CWD name resolves to CWD.
- No nested `.agent` directories are created.
- Tests pass after the change.

## Rollout Notes
- No file format or state migration changes required.