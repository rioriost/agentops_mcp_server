# Implementation Plan: 0.4.9 Legacy journal init fix

## Objectives
- Stop `zed-agentops-init.sh` from creating `.agent/journal.jsonl` during initialization.
- Preserve legacy artifact recognition for `journal.jsonl` so older workspaces can still be detected and handled safely.
- Keep the change small, localized, and aligned with the canonical artifact model.

## Background
Current behavior still creates `.agent/journal.jsonl` as a legacy artifact in the initialization script. That is no longer desired.

The intended behavior for `0.4.9` is:
- `journal.jsonl` remains a known legacy filename for compatibility checks.
- Fresh initialization should only create the canonical and derived artifacts that are still part of the current contract.
- Startup and repository-context behavior should continue to recognize legacy artifacts without treating them as required initialization output.

## Scope
### In scope
- Remove legacy journal file creation from `zed-agentops-init.sh`
- Update tests that currently allow or imply creation of `.agent/journal.jsonl`
- Add or adjust release ticket metadata for this small fix

### Out of scope
- Runtime migration of existing legacy files
- Broader cleanup of all legacy artifact handling
- Changes to canonical transaction files or derived artifact semantics

## Phases

### Phase 1: Plan and metadata alignment
**Goals**
- Record the release intent for the small fix.
- Keep ticket metadata consistent with the implementation scope.

**Tasks**
- Add `docs/v0.4.9/plan.md`
- Add `docs/v0.4.9/tickets_list.json`
- Add one focused ticket for the initialization-script change and verification

**Deliverables**
- Minimal `0.4.9` planning artifacts for the fix

---

### Phase 2: Implementation and verification
**Goals**
- Remove unnecessary legacy journal creation while keeping compatibility checks intact.
- Verify that initialization expectations remain correct.

**Tasks**
- Update `src/agentops_mcp_server/zed-agentops-init.sh` to stop creating `.agent/journal.jsonl`
- Preserve legacy filename knowledge in Python code where compatibility checks rely on it
- Update tests to assert that canonical and derived artifacts are present without requiring legacy journal creation
- Run repository verification

**Deliverables**
- Updated initialization script
- Updated regression tests
- Verified small-scope release change

## Acceptance Criteria
- `zed-agentops-init.sh` does not create `.agent/journal.jsonl`
- Legacy artifact recognition for `journal.jsonl` remains available for compatibility checks
- Tests and verification pass after the change

## Rollout Notes
- Keep the implementation minimal.
- Do not reintroduce `journal.jsonl` as an initialized artifact.
- Treat this as a compatibility-preserving cleanup, not a transaction-model change.

## Completion Summary
- Removed legacy `.agent/journal.jsonl` creation from `zed-agentops-init.sh`.
- Kept legacy `journal.jsonl` recognition in runtime code for compatibility checks.
- Updated initialization-focused tests so fresh setup asserts only current canonical and derived artifacts.
- Verified the targeted regression tests pass for the v0.4.9 change.