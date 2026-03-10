# Implementation Plan: 0.3.0 Class-based refactor for `main.py`

## Objectives
- Split `main.py` into class-based components to improve maintainability.
- Preserve external behavior (tool call inputs/outputs remain identical).

## Assumptions
- Refactor is internal only; public tool schemas and JSON-RPC behavior remain unchanged.
- Existing test suite is the baseline for behavior validation.

## Phases

### Phase 1: Design & mapping
**Goals**
- Identify seams for class extraction.
- Define responsibilities and boundaries.

**Tasks**
- Audit `main.py` for cohesive responsibilities (IO, routing, tool registry, state/persistence).
- Draft class boundaries and shared interfaces.
- Identify any risky behavior changes to avoid.

---

### Phase 2: Implementation (class extraction)
**Goals**
- Move logic into classes while keeping behavior stable.

**Tasks**
- Introduce minimal classes (e.g., `ToolRouter`, `StateStore`, `Runner`) and migrate logic.
- Keep module-level API functions as thin wrappers where needed.
- Refactor in small, verifiable steps.

---

### Phase 3: Verification & regression
**Goals**
- Confirm behavior matches 0.2.3 externally.

**Tasks**
- Run `${VERIFY_REL}` and compare outputs for critical paths.
- Update/add tests for new class boundaries if required.
- Re-check tool call and result parity.

## Acceptance Criteria Mapping
- External tool behavior unchanged (request/response parity).
- Tests pass after refactor.

## Rollout Notes
- Avoid schema changes unless required by internal refactor.
- Keep logging and error handling consistent with 0.2.3.