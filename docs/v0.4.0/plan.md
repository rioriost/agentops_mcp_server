# Implementation Plan: 0.4.0 Transaction-Aware Task Managing (Breaking Redesign)

## 0.4.0 Positioning
- This release is a **breaking redesign**.
- **Backward compatibility is intentionally out of scope**.
- Legacy persistence assumptions and schemas may be removed or replaced.

## Objectives
- Make interrupted-session resume deterministic and robust.
- Treat each ticket as a first-class transaction with explicit lifecycle boundaries.
- Persist fine-grained intent: which files are changed, for what purpose, and in what sequence.
- Replace fragmented resumability semantics with a coherent, transaction-centric model.
- Reach and maintain test coverage >= 90%.

## Scope

### In scope
- Persistence architecture redesign for interruption recovery.
- Transaction model for ticket lifecycle.
- State schema redesign and artifact simplification.
- Recovery algorithm redesign and precedence rules.
- `.rules` redesign to align with transaction-aware execution.
- Verification strategy for interruption cut points and replay determinism.

### Out of scope
- Preserving old schema compatibility.
- Migration shims for old resumability consumers.
- Non-resume-related feature work.

---

## 1) Problem Statement (Normalized)
Current system weaknesses:
1. During `in-progress`, multiple file operations occur without durable per-file intent semantics.
2. Existing safety sequence improves timing of persistence but not enough semantic depth for exact resume.
3. Resume sources are split across multiple artifacts with overlapping concerns.
4. Divergence/torn-state handling is under-specified under abrupt interruption.
5. Ticket lifecycle is not modeled as a transaction, making deterministic continuation harder.

Consequence:
- After interruption, resumed session can know “something happened,” but not always “exactly what to do next.”

---

## 2) Design Principles (0.4.0)

1. **Transaction-first execution**
   - Ticket is the primary transactional unit.

2. **Deterministic resume**
   - Same persisted state must always produce same resumed ticket and next step.

3. **Single canonical state model**
   - Eliminate ambiguous overlap among state artifacts.

4. **Event + materialized state coherence**
   - Event history and materialized transaction state must be mutually reconstructable.

5. **Atomicity-aware writes**
   - Persist boundaries and sequencing to minimize torn-state ambiguity.

6. **Operational clarity**
   - Keep structures compact but semantically complete.

---

## 2.1) Reference Philosophy (Conceptual Foundations)

The canonical two-layer model is based on well-established distributed systems and data architecture concepts, adapted to agent task resumption:

1. **Event Sourcing mindset**
   - Persist domain-relevant transitions as append-only events.
   - In this plan, transaction progress is captured as durable event history first.

2. **Materialized View / CQRS-style read model**
   - Maintain a current-state projection optimized for fast resume decisions.
   - In this plan, materialized transaction state provides immediate `next_action` recovery.

3. **Log-first durability discipline (WAL-like ordering)**
   - Record intent/progress in durable history before updating derived state.
   - This reduces ambiguity when interruption occurs mid-write.

4. **State machine driven workflow execution**
   - Model ticket lifecycle and step transitions explicitly with invariants.
   - This ensures replay and resume remain deterministic and testable.

5. **Separation of canonical truth vs convenience views**
   - Canonical truth: transaction event log + materialized transaction state.
   - Convenience view: human-readable handoff, always regenerable from canonical sources.

These principles are not tied to a specific product implementation; they are design references used to justify why the 0.4.0 model prioritizes deterministic recovery over backward compatibility.

---

## 3) Target Architecture (Breaking)

## 3.1 Canonical artifacts (proposed)
Adopt a new 2-layer model:

1. **Transaction Event Log** (append-only)
   - Canonical history of ticket transaction events.

2. **Materialized Transaction State**
   - Canonical latest state for fast resume (derived from log + checkpoints).

Optional:
- Human-readable handoff becomes **derived view only**, not canonical persistence source.

### Canonical artifact output path policy
- Reuse the current output path decision logic from the existing implementation.
- Canonical artifacts are written under `CWD/.agent/`.
- No new path resolution mechanism is introduced in 0.4.0; only schema/semantics are redesigned.

## 3.2 Legacy artifact treatment
- Previous four-way model (`journal/checkpoint/snapshot/handoff`) is not required to remain as-is.
- 0.4.0 may:
  - Merge old snapshot/handoff semantics into a unified state document.
  - Replace checkpoint semantics with embedded cursor/offset in state.
  - Keep compatibility only where internally useful, not externally guaranteed.

---

## 4) Transaction Model for Tickets

## 4.1 Transaction lifecycle
- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

Each ticket transaction includes explicit boundaries:
- `tx.begin`
- `tx.step.enter`
- `tx.file_intent.add|update|complete`
- `tx.verify.start|pass|fail`
- `tx.commit.start|done|fail`
- `tx.end.done|blocked`

## 4.2 Transaction invariants
- Exactly one active transaction per worker/session execution context.
- `tx.begin` must exist before any file mutation events.
- File mutation events must reference an existing file-intent entry.
- `tx.end.*` is terminal for that transaction id.
- Resume must target the latest non-terminal transaction.

---

## 5) Canonical Schema (0.4.0)

## 5.1 Event log record (conceptual)
- `seq`
- `ts`
- `tx_id`
- `ticket_id`
- `event_type`
- `phase`
- `step_id`
- `payload`
- `actor`
- `session_id`

## 5.2 Materialized transaction state (conceptual)
- `schema_version` (e.g. `0.4.0`)
- `active_tx`
  - `tx_id`
  - `ticket_id`
  - `status`
  - `phase`
  - `current_step`
  - `last_completed_step`
  - `next_action`
  - `verify_state`
  - `commit_state`
  - `file_intents[]`
    - `path`
    - `operation`
    - `purpose`
    - `state` (`planned|started|applied|verified`)
    - `last_event_seq`
- `last_applied_seq`
- `integrity`
  - `state_hash`
  - `rebuilt_from_seq`
- `updated_at`

## 5.3 File-intent semantics
Before first mutation of any file in `in-progress`, intent must exist:
- target path
- operation type
- semantic purpose
- planned step association

This is mandatory for deterministic resumption.

---

## 6) Persistence and Write Ordering

For each ticket progress action:
1. Append transaction event(s) to log.
2. Update materialized transaction state.
3. Persist state cursor (`last_applied_seq`) atomically with state snapshot.
4. Optionally regenerate human-readable handoff view from canonical state.

### Torn-state recovery policy
- Event log is primary history.
- Materialized state is authoritative only if integrity checks pass.
- On mismatch:
  - rebuild materialized state from event log up to highest durable sequence,
  - recompute handoff view.

---

## 7) Recovery Algorithm (Session Resume)

At session start:
1. Load materialized transaction state.
2. Validate integrity and cursor coherence.
3. If invalid or stale, rebuild from event log.
4. Find latest non-terminal transaction.
5. Derive exact `next_action` from:
   - status
   - step markers
   - file-intent states
   - verify/commit states
6. Resume from deterministic boundary and emit `tx.step.enter` continuation event.

Failure modes:
- If no active non-terminal transaction: start next planned ticket.
- If corrupted tail events: truncate to last valid sequence and rebuild.

---

## 8) `.rules` Redesign for 0.4.0

Rules must explicitly require:

1. Ticket transaction boundaries for every unit of work.
2. Per-file intent registration before mutation.
3. Transaction event emission for step transitions and verification/commit milestones.
4. Canonical state capture after each mutation-affecting step.
5. Resume precedence: canonical state + event log only.
6. Derived handoff generation only as convenience, never as source of truth.

---

## 9) Phased Execution Plan

## Phase 1: Architecture freeze
Goals:
- Finalize transaction model and canonical schema.
Tasks:
- Finalize event taxonomy and lifecycle invariants.
- Finalize canonical state schema and integrity model.
- Finalize resume algorithm and torn-state policy.
Outputs:
- Architecture spec and schema spec docs.

## Phase 2: Runtime redesign specification
Goals:
- Define implementation blueprint.
Tasks:
- Define writer pipeline (event append -> state update -> cursor persist).
- Define rebuild engine from event log.
- Define transaction selection/resume logic.
- Define removal/replacement of legacy artifact paths.
Outputs:
- Component change checklist and dataflow spec.

## Phase 3: Test strategy and verification gates
Goals:
- Prove deterministic interruption recovery.
Tasks:
- Build interruption matrix:
  - before first file mutation
  - between intent registration and mutation
  - after mutation before state persist
  - after state persist before verify
  - after verify before commit
  - after commit before terminal event
- Add replay/rebuild determinism tests.
- Add integrity mismatch recovery tests.
- Run verification and ensure coverage >= 90%.
Outputs:
- Resilience test suite + coverage report.

---

## 10) Acceptance Criteria Mapping
1. Interrupted session resumes the exact active transaction and correct next action.
2. Every mutated file in `in-progress` is associated with durable purpose/intent metadata.
3. Rebuild from event log yields equivalent materialized state for the same sequence boundary.
4. Torn-state situations resolve deterministically via defined recovery policy.
5. Coverage >= 90%.

---

## 11) Risks and Mitigations
- Risk: Complexity increase from transaction model.
  - Mitigation: strict schema boundaries and event taxonomy.
- Risk: Event volume growth.
  - Mitigation: concise payload design + periodic compaction strategy.
- Risk: Rebuild performance degradation.
  - Mitigation: bounded snapshots and cursor checkpoints.
- Risk: Implementation drift from rules.
  - Mitigation: rule assertions mirrored in tests.

---

## 12) Rollout Strategy (Breaking)
- Introduce new schema and runtime path as default in 0.4.0.
- Remove dependence on old compatibility contracts.
- Validate through interruption stress scenarios before final release.
- Document new operational semantics as 0.4.0 baseline.

## Final Note
This 0.4.0 plan prioritizes correctness and determinism over compatibility. It explicitly reframes ticket execution as a transaction system so interruption recovery is exact, explainable, and testable.