# Implementation Plan: Refactor main.py and improve test coverage

## Objectives
- Reduce duplication in `main.py` through targeted refactoring.
- Update tests to match refactored behavior.
- Achieve >= 90% coverage.

## Assumptions
- `main.py` can be reorganized without changing public tool behavior.
- Coverage is measured by the existing pytest configuration.

## Phases

### Phase 1: Discovery & design
**Goals**
- Identify duplicated logic in `main.py`.
- Define refactor approach that minimizes behavior changes.

**Tasks**
- Audit `main.py` for repeated patterns (parsing, I/O, error handling, schema wiring).
- Define helper functions and shared utilities to consolidate duplication.
- Identify tests that will need updates or additions.

---

### Phase 2: Refactor implementation
**Goals**
- Reduce duplication while preserving external behavior.

**Tasks**
- Extract shared helpers for repeated logic.
- Simplify tool registry handling and common request/response flows.
- Refactor in small, verifiable steps.

---

### Phase 3: Tests & coverage
**Goals**
- Ensure tests align with refactor.
- Reach coverage >= 90%.

**Tasks**
- Update existing tests for refactored behavior.
- Add tests for newly extracted helpers and critical code paths.
- Run `${VERIFY_REL}` and review coverage output.

## Acceptance Criteria Mapping
- Code size reduction is demonstrable (diff stats).
- Coverage >= 90%.
- Tests pass after refactor.

## Rollout Notes
- Refactor is internal; no API changes expected.
- Keep behavior identical unless explicitly required by tests.