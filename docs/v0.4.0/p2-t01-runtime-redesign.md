# 0.4.0 Runtime Redesign Overview

This document summarizes the runtime redesign for 0.4.0, focusing on the canonical event log + materialized state pipeline and deterministic resume behavior. It is an implementation blueprint derived from `docs/v0.4.0/plan.md`.

## Goals

- Deterministic recovery from interruption at any boundary.
- Canonical truth in event log + materialized transaction state.
- Transaction-first execution with explicit lifecycle boundaries.
- Eliminate ambiguity between legacy artifacts; new model is authoritative.

## Canonical Artifacts

1. **Transaction Event Log (append-only)**
   - Canonical history of transaction events.
   - Requires strict ordering; written before any derived state.

2. **Materialized Transaction State**
   - Latest state projection for fast resume.
   - Includes cursor (`last_applied_seq`) and integrity metadata.

3. **Derived Views (optional)**
   - Human-readable handoff or summaries.
   - Non-canonical and fully regenerable.

## Runtime Responsibilities

- Emit transaction events for lifecycle boundaries, file intents, verify/commit milestones, and persistence checkpoints.
- Update materialized state after event append, respecting ordering.
- Persist cursor + integrity metadata atomically with state.
- Provide deterministic resume from the latest non-terminal transaction.

## Execution Flow (High Level)

1. **tx.begin**
2. **tx.step.enter**
3. **tx.file_intent.add / start / apply**
4. **tx.state.persist**
5. **tx.verify.start / pass|fail**
6. **tx.commit.start / done|fail**
7. **tx.end.done|blocked**

Every step is logged to the event log before state mutation.

## Resume Strategy

- Load materialized state and validate integrity.
- If invalid or stale, rebuild from event log up to last durable sequence.
- Select latest non-terminal transaction.
- Derive `next_action` from:
  - status
  - step markers
  - file intent states
  - verify/commit states
  - last applied sequence

## Legacy Artifact Replacement

- Snapshot/handoff/checkpoint/journal roles are consolidated into:
  - Event log + materialized state (canonical)
  - Optional derived handoff
- No compatibility shims required for 0.4.0.

## Determinism Guarantees

- Event log is the single source of truth.
- Materialized state must be rebuildable from log.
- Cursor (`last_applied_seq`) defines the exact deterministic recovery boundary.