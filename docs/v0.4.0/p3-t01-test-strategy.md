# 0.4.0 Phase 3 Test Strategy Overview

This document defines the Phase 3 test strategy for 0.4.0. It focuses on deterministic interruption recovery, replay/rebuild correctness, integrity mismatch handling, and verification gates aligned to the transaction-aware model.

## Goals

- Prove deterministic resume at every interruption boundary.
- Validate rebuild correctness from the event log.
- Confirm integrity mismatch recovery resolves to a single deterministic state.
- Enforce verification gates and coverage target (>= 90%).

## Scope

This strategy covers **specification** of tests and gates only. It does not implement tests.

## Test Categories

### 1) Interruption Recovery Matrix
Validate resume behavior when interruption occurs at critical cut points (detailed in the interruption matrix document).

Key checks:
- Correct transaction selection (latest non-terminal).
- Correct `next_action` derivation.
- No lost file intents or skipped lifecycle events.

### 2) Replay / Rebuild Determinism
Validate that replaying the same event log yields identical materialized state.

Key checks:
- `state_hash` matches across rebuilds.
- `last_applied_seq` respected and stable.
- Derived `next_action` identical for same sequence.

### 3) Integrity Mismatch Recovery
Validate that corrupt or stale state is discarded and rebuilt deterministically.

Key checks:
- Integrity validation failures trigger rebuild.
- Rebuild stops at last valid sequence on corruption.
- Derived state matches expected post-rebuild boundary.

### 4) Verification Gates & Coverage
Define explicit gates used to accept Phase 3 readiness.

Key checks:
- `${VERIFY_REL}` must pass.
- Coverage threshold >= 90% in configured test suite.
- Test artifacts recorded for reproducibility.

## Required Artifacts

- Interruption matrix definition
- Determinism test definitions
- Integrity mismatch scenarios
- Verification gate checklist

## Success Criteria

- All interruption cut points covered.
- Deterministic rebuild proven with consistent state hashes.
- Integrity mismatches resolve to deterministic, documented outcomes.
- Coverage and verification gates are explicit and measurable.