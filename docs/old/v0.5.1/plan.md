# Implementation Plan: 0.5.1 Reliable `.rules` generation for `zed-agentops-init`

## Objectives
- Fix the bootstrap bug that can prevent `zed-agentops-init` from writing `.rules` when invoked from an arbitrary current working directory.
- Replace current-directory-dependent rule asset lookup with script-relative lookup based on `BASH_SOURCE[0]`.
- Preserve existing initialization behavior for `.agent`, `.gitignore`, `.zed`, and `.rules` overwrite/update semantics.
- Ensure installed-package usage and source-tree usage behave consistently.

## Background
Version 0.5.0 established a stronger single-source-of-truth model for workflow rules by introducing:

- repository `.rules`,
- canonical rules generation via `workflow_rules.py`,
- packaged fallback rules via `workflow_rules_fallback.txt`,
- and workspace bootstrap through `zed-agentops-init.sh`.

That model is correct in principle, but the current init script still resolves workflow rule sources using `${PWD}`. This creates a packaging/runtime mismatch:

- repository-local execution can succeed because the expected source-tree paths exist,
- installed execution can fail because `${PWD}` is the caller’s working directory rather than the package resource location.

As a result, `.rules` generation is not reliable in the installed command path, even though the necessary packaged assets are present.

## Problem Statement
The current `zed-agentops-init.sh` uses `${PWD}` to resolve workflow rule inputs such as:

- `${PWD}/.rules`
- `${PWD}/src/agentops_mcp_server/workflow_rules.py`
- `${PWD}/src/agentops_mcp_server/workflow_rules_fallback.txt`

This is incorrect for packaged execution because `${PWD}` is not a stable reference to bundled resources.

The correct runtime anchor is the script’s own directory, since the packaged shell script and fallback rules file are distributed together and should be resolved relative to one another.

## Scope

### In scope
- Update `zed-agentops-init.sh` to resolve rule assets relative to the script location.
- Preserve current `.rules` write/skip/update behavior in target workspaces.
- Preserve source-tree execution compatibility.
- Add regression tests for installed-style invocation and script-relative asset resolution.
- Document the fix through release planning artifacts.

### Out of scope
- Changing the content of canonical workflow rules.
- Redesigning `.rules` overwrite policy.
- Reworking transaction semantics or `.agent` bootstrap behavior.
- Introducing a new environment-variable-based resource contract.
- Broad packaging redesign unrelated to rule asset lookup.

## Implementation Strategy
The fix for 0.5.1 should follow a simple rule:

> packaged rule assets must be located relative to the init script itself, not relative to the caller’s current working directory.

This means the script should:
1. determine its own path using `BASH_SOURCE[0]`,
2. derive its containing directory,
3. resolve adjacent packaged assets from that directory,
4. use those script-relative assets as the primary source for `.rules` generation.

Where development-time compatibility requires it, source-tree fallbacks may still be supported, but packaged/script-relative resolution must become the authoritative runtime path.

## Phases

### Phase 1: Define the script-relative resource lookup contract
**Goals**
- Make the intended lookup model explicit before modifying behavior.
- Ensure the init script has one correct runtime anchor for packaged assets.

**Tasks**
- Identify every place in `zed-agentops-init.sh` where rule asset lookup depends on `${PWD}`.
- Define the canonical script-relative lookup model based on `BASH_SOURCE[0]`.
- Decide which assets must be expected adjacent to the script at runtime.
- Preserve the current fallback ordering only where it still makes sense under the new script-relative model.

**Deliverables**
- Explicit script-relative lookup design for workflow rules.
- Removal plan for `${PWD}`-anchored rule discovery.

---

### Phase 2: Implement script-relative `.rules` source resolution
**Goals**
- Make `.rules` generation reliable under installed execution.
- Keep the user-visible behavior of init/update flows unchanged.

**Tasks**
- Compute the absolute script path from `BASH_SOURCE[0]`.
- Derive the script directory early in `zed-agentops-init.sh`.
- Replace `${PWD}`-based workflow rule source paths with script-relative paths.
- Prefer the packaged fallback rules file when present alongside the script.
- Retain compatibility paths only as needed for source-tree development execution.
- Keep existing logic for:
  - skipping non-file `.rules`,
  - skipping existing `.rules` on non-update initialization,
  - backing up existing `.rules` during update mode,
  - writing resolved rules into `root/.rules`.

**Deliverables**
- Updated `zed-agentops-init.sh` with script-relative rule asset lookup.
- Stable `.rules` generation path for installed usage.

---

### Phase 3: Preserve source-tree compatibility and packaging assumptions
**Goals**
- Ensure the fix does not regress repository-local execution.
- Keep release packaging aligned with the new runtime assumptions.

**Tasks**
- Verify that direct execution of `src/agentops_mcp_server/zed-agentops-init.sh` still works from the repository.
- Confirm that the packaged fallback rules asset remains sufficient for installed execution.
- Review packaging configuration to ensure required rule assets remain included in wheel/sdist outputs.
- Avoid introducing a dependency on repository-only paths during installed execution.

**Deliverables**
- Source-tree-compatible init behavior.
- Packaging assumptions documented and preserved.

---

### Phase 4: Add regression coverage for the bootstrap path bug
**Goals**
- Lock in the fix with tests that would have failed under the old `${PWD}` model.
- Verify both implementation details and observable behavior.

**Tasks**
- Add tests that validate the init script no longer depends on `${PWD}` for packaged rule asset lookup.
- Add tests that validate script-relative lookup is present in the init script.
- Add tests that simulate invocation from an unrelated current working directory.
- Add tests that verify `.rules` is created in the target project under that invocation pattern.
- Keep coverage focused on the regression and packaging/runtime behavior, not unrelated bootstrap refactors.

**Deliverables**
- Regression tests for installed-style invocation.
- Coverage that guards against reintroducing current-directory-dependent lookup.

## Acceptance Criteria

### Functional behavior
- Running `zed-agentops-init <project>` from an arbitrary current working directory writes `<project>/.rules`.
- Running `zed-agentops-init --update <project>` from an arbitrary current working directory updates `<project>/.rules` as intended.
- Running `src/agentops_mcp_server/zed-agentops-init.sh <project>` from the repository continues to write `<project>/.rules`.

### Path resolution behavior
- Workflow rule asset discovery no longer depends on `${PWD}`.
- Packaged assets are resolved relative to the script’s own location.
- Installed execution no longer assumes the caller’s working directory contains repository source paths.

### Bootstrap stability
- Existing `.rules` skip/backup/update semantics remain unchanged.
- Existing `.agent`, `.gitignore`, and `.zed` scaffold behavior remains intact.

### Packaging compatibility
- Required rule assets remain available in release artifacts.
- Installed execution succeeds without requiring `src/agentops_mcp_server/...` paths in the caller’s current directory.

## Risks

### Low functional risk
The change is localized to workflow-rule source resolution in the init script.

### Medium packaging risk
If script-relative lookup is implemented incorrectly, installed bootstrap may still fail. This is mitigated by:
- keeping the fallback rules text packaged,
- testing invocation outside the repository root,
- and validating the packaged-resource assumption directly.

### Low behavioral risk
The intended behavior of target workspace creation should remain unchanged except for fixing missing `.rules`.

## Validation Plan
After implementation, validation should include:

1. repository-local execution of the init shell script,
2. installed-entrypoint execution from an unrelated current working directory,
3. target workspace verification that `.rules` exists,
4. update-mode verification that `.rules` backup/overwrite behavior remains correct,
5. regression test execution covering the new lookup strategy.

## Ticket Breakdown

### Ticket `p1-t01`
**Title:** Refactor init script to resolve workflow rule assets relative to `BASH_SOURCE[0]`  
**Priority:** P0  
**Summary:** Replace `${PWD}`-based workflow rule source lookup in `zed-agentops-init.sh` with script-relative lookup derived from `BASH_SOURCE[0]`, while preserving existing `.rules` target write behavior.

### Ticket `p1-t02`
**Title:** Preserve source-tree and packaged fallback compatibility for init rules generation  
**Priority:** P1  
**Summary:** Ensure the new script-relative lookup works both for installed package execution and repository-local execution, and confirm packaged fallback assets remain sufficient.

### Ticket `p2-t01`
**Title:** Add regression coverage for installed-style `.rules` bootstrap behavior  
**Priority:** P1  
**Summary:** Add tests that verify `.rules` is created when the init command is invoked from an unrelated current working directory and that the script no longer relies on `${PWD}` for packaged rule asset discovery.

## Expected Outcome
After 0.5.1:

- `zed-agentops-init` will reliably create `.rules`,
- installed execution will behave the same as source-tree execution for workflow rule provisioning,
- the bootstrap path will no longer depend on where the user runs the command from,
- and the packaged init flow will match the intended release model.

## Summary
Version 0.5.1 should fix a bootstrap reliability bug in `zed-agentops-init.sh` by replacing `${PWD}`-based workflow rule lookup with script-relative lookup anchored on `BASH_SOURCE[0]`.

This plan keeps the change narrowly scoped, preserves existing target workspace semantics, and adds the regression coverage needed to prevent the issue from returning.