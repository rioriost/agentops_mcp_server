# Implementation Plan: 0.4.5 bug fixes for tx_event_log initialization

## 0.4.5 Positioning
- Starting a job with an empty `tx_event_log.jsonl` (touched only) triggers errors.
- An empty log should be treated as the initial state created by `zed-agentops-init.sh`.
- Tool call inputs for `tx_event_append` and `tx_state_save` must be handled consistently at initialization.

## Objectives
- Treat empty `tx_event_log.jsonl` as a valid initial state.
- Ensure initialization does not fail when the log is empty.
- Align tool expectations for `tx_event_append` and `tx_state_save` with initialization flows.
- Maintain coverage >= 90%.

---

## 1) Problem Statement (Normalized)
1. Jobs started with an empty `tx_event_log.jsonl` fail early.
2. Initialization does not clearly distinguish between “missing log” and “empty log”.
3. Tool input requirements (`actor`, `payload`, `state`) are strict and can block init flows.

---

## 2) Design Principles (0.4.5)
1. **Init-safe by default**
   - Empty log should be accepted as a valid initial state.
2. **Single source of truth**
   - Initialization should be derived consistently from log/state files.
3. **Minimal safe change**
   - Target init handling and tool input expectations only.
4. **Coverage preservation**
   - Keep test coverage >= 90%.

---

## 3) Target Changes

### 3.1 Empty tx_event_log handling
- Treat empty `tx_event_log.jsonl` the same as “no events yet”.
- Ensure rebuild and state checks do not error on empty logs.

### 3.2 Initialization state handling
- Ensure initialization derives a baseline tx_state when the log is empty.
- Avoid requiring manual tx_event inputs to reach a valid baseline.

### 3.3 Tool input alignment
- Align `tx_event_append` and `tx_state_save` expectations with init flows.
- Provide clearer error messages or safe defaults for initialization paths.

### 3.4 `.rules` guidance
- Update `.rules` to specify required inputs for `tx_event_append` and `tx_state_save`.

### 3.5 Tests & coverage
- Add tests for empty log initialization behavior.
- Add tests for `tx_event_append`/`tx_state_save` inputs in init scenarios.
- Validate coverage >= 90%.

---

## 4) Phases & Tasks

### Phase 1: Analysis & Planning
- **p1-t1**: Inventory initialization and tx_event_log usage paths.
- **p1-t2**: Draft initialization handling plan and tool input alignment.

### Phase 2: Implementation
- **p2-t1**: Implement empty-log initialization handling.
- **p2-t2**: Align tool input handling for `tx_event_append` and `tx_state_save`.
- **p2-t3**: Update init script or state defaults if needed.

### Phase 3: Policy & Rules
- **p3-t1**: Update `.rules` for tool input requirements.
- **p3-t2**: Add tests for rule-influenced expectations (if applicable).

### Phase 4: Tests & Verification
- **p4-t1**: Add unit/integration tests for empty log initialization.
- **p4-t2**: Run verification suite and confirm coverage >= 90%.

---

## 5) Acceptance Criteria
- Jobs start successfully when `tx_event_log.jsonl` is empty.
- Initialization builds a valid baseline state without errors.
- Tool input expectations are aligned with init flows.
- Test coverage >= 90% and tests pass.

---

## 6) Risks & Mitigations
- **Risk:** Over-permissive tool defaults weaken validation.
  - **Mitigation:** Limit defaults to init scenarios and keep errors explicit elsewhere.
- **Risk:** Hidden init paths not covered.
  - **Mitigation:** Inventory all log/state entry points and add tests.

---

## 7) Deliverables
- `docs/v0.4.5/plan.md`
- `docs/v0.4.5/tickets_list.json`
- `docs/v0.4.5/pX-tY.json` tickets
- Source updates for init handling and tool input alignment
- Tests covering empty log initialization