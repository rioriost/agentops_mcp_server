# Implementation Plan: 0.3.1 Refactor main.py continued

## Objectives
- Complete class-based refactor across all remaining `main.py` responsibilities.
- Split classes into separate modules/files while preserving external behavior.
- Maintain tool call inputs/outputs identical to 0.2.3.

## Assumptions
- Refactor is internal only; public tool schemas and JSON-RPC behavior remain unchanged.
- Existing tests will be largely rewritten to match the refactor.

## Phases

### Phase 1: Analysis & design
**Goals**
- Identify remaining non-class responsibilities in `main.py`.
- Define final class boundaries and file layout.

**Tasks**
- Audit `main.py` for remaining cohesive responsibilities.
- Map classes to new module files with minimal coupling.
- Note any risky behavior changes to avoid.

---

### Phase 2: Implementation (class extraction + file split)
**Goals**
- Move remaining logic into classes and split by file.
- Keep module-level entrypoints stable and thin.

**Tasks**
- Extract remaining functions into classes.
- Create new module files per class and move implementations.
- Update imports and wiring without changing behavior.

---

### Phase 3: Verification & regression
**Goals**
- Ensure behavior parity with 0.2.3.

**Tasks**
- Rewrite most tests impacted by the refactor and rebuild the baseline.
- Run `${VERIFY_REL}` and review results.
- Ensure coverage >= 90%.
- Spot-check critical tool call flows for parity.

## Acceptance Criteria Mapping
- External tool behavior unchanged (request/response parity).
- Tests pass after refactor.
- Coverage >= 90%.

## Rollout Notes
- Avoid any schema or API changes.
- Keep logging and error handling consistent with 0.2.3.