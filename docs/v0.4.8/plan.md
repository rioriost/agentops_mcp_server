# Implementation Plan: 0.4.8 Initial-state startup bug fixes

## Objectives
- Eliminate startup errors when work begins from a freshly initialized `.agent` baseline.
- Align initialization, runtime behavior, and operator guidance across `.rules`, `zed-agentops-init.sh`, and Python implementation.
- Preserve strict transaction ordering while allowing planning work to begin safely from an initial zero-event state.
- Maintain at least 90% test coverage.

## Background
The updated draft identifies failures that occur immediately after initializing a project and opening it in Zed:

- `ops_start_task` fails with `tx.begin required before other events`
- `ops_update_task` fails for the same ordering reason during planning startup
- `ops_capture_state` fails because `active_tx.next_action` is missing
- `ops_handoff_export` fails for the same `next_action` requirement

These errors indicate a mismatch between:
1. the expected canonical transaction lifecycle,
2. the initial files created by the setup script, and
3. the runtime assumptions in the Python implementation.

## Assumptions
- The strict transaction model remains valid and should not be weakened globally.
- A present-but-empty canonical event log is a valid initialized baseline.
- Planning flow must be able to start from that baseline without manual repair.
- `docs/draft.md` is the authoritative source for this release plan.
- Existing behavior outside the startup/resume path should remain stable.

## Scope
### In scope
- `.rules` consistency updates for initial-state startup expectations
- `zed-agentops-init.sh` initialization behavior and generated rule template
- Python runtime fixes under `src/`
- Regression tests for startup, capture, handoff, and planning bootstrap behavior
- Verification of coverage target

### Out of scope
- Unrelated transaction-model redesign
- New user-facing features beyond startup robustness
- Large schema changes unless strictly required to satisfy startup correctness

## Phases

### Phase 1: Root-cause analysis and contract alignment
**Goals**
- Identify the exact mismatch between initialization artifacts, rules, and runtime expectations.
- Define the canonical startup contract for a zero-event baseline.

**Tasks**
- Inspect `.rules` requirements for startup, restore order, and task lifecycle ordering.
- Inspect `zed-agentops-init.sh` output and generated guidance.
- Inspect Python code paths that read active transaction state, derive `next_action`, and enforce `tx.begin`.
- Document the intended behavior for:
  - empty canonical event log
  - no active transaction
  - first planning task bootstrap
  - handoff/state capture before work begins

**Deliverables**
- Agreed startup contract for initial-state execution
- Concrete list of mismatches to fix in infra and runtime

---

### Phase 2: Runtime and initialization fixes
**Goals**
- Make startup from the initialized baseline succeed without transaction-ordering errors.
- Ensure derived state remains valid even when no active work has started.

**Tasks**
- Update Python logic so the first planning/task-start path can safely establish transaction context when appropriate.
- Ensure state capture and handoff generation tolerate an initial no-active-work baseline and produce a valid next step.
- Update `zed-agentops-init.sh` so created files and embedded rule text match runtime expectations.
- Update `.rules` text where needed so it describes the intended bootstrap flow precisely.

**Deliverables**
- Corrected Python behavior in `src/`
- Updated initialization script behavior/template
- Updated rule text aligned with runtime behavior

---

### Phase 3: Regression tests and verification
**Goals**
- Prevent recurrence of the startup failures.
- Prove the release satisfies the draft acceptance criteria.

**Tasks**
- Add/extend tests covering:
  - initial zero-event baseline startup
  - first planning task start
  - transaction bootstrap ordering
  - state capture on initial baseline
  - handoff export on initial baseline
  - setup script contract expectations
- Run the full verification flow.
- Measure and confirm coverage remains at or above 90%.

**Deliverables**
- Regression tests for all reported failures
- Verification evidence for passing tests and coverage target

## Acceptance Criteria Mapping
- **Initial state starts without errors**  
  Covered by Phase 2 bootstrap/state fixes and Phase 3 regression tests.
- **Coverage 90%+**  
  Covered by Phase 3 verification and coverage measurement.

## Risks and Mitigations
- **Risk:** Relaxing transaction rules too broadly could hide invalid event sequences.  
  **Mitigation:** Limit bootstrap handling to the initial no-active-transaction baseline only.

- **Risk:** Rules text, setup script output, and Python behavior may drift again.  
  **Mitigation:** Add tests that assert contract-level expectations for initialization and startup.

- **Risk:** Derived artifacts may still assume fields that are absent in baseline state.  
  **Mitigation:** Ensure defaults for startup-safe derived values such as `next_action`.

## Verification Strategy
- Run the project verification command used by the repository.
- Run tests with coverage reporting.
- Confirm that startup-specific regression cases pass.
- Confirm total coverage remains at least 90%.

## Rollout Notes
- Keep changes minimal and focused on startup correctness.
- Prefer contract-preserving fixes over broad lifecycle redesign.
- Treat `.agent/handoff.json` as derived output and canonical transaction files as the source of truth.