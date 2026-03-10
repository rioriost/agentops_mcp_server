# Phase 0 Implementation Map for 0.6.0

## Purpose

This document is the phase 0 analysis artifact for the `0.6.0` redesign described in `docs/v0.6.0/plan.md`. It consolidates the outputs expected by:

- `p0-t01` Review all Python files under `src` and build an implementation map
- `p0-t02` Map persistence artifacts and their read/write code paths
- `p0-t03` Map begin, resume, and active-transaction selection code paths

It is intentionally descriptive only. It does not propose runtime changes as committed facts, and it does not alter protocol behavior.

---

## High-level codebase map

### Runtime composition

The runtime is centered around a small set of modules under `src/agentops_mcp_server/`:

- entrypoint and wiring:
  - `main.py`
  - `tool_registry.py`
  - `tool_router.py`
  - `json_rpc_server.py`
- repository and shell integration:
  - `repo_context.py`
  - `git_repo.py`
  - `verify_runner.py`
  - `repo_tools.py`
  - `commit_manager.py`
- canonical transaction persistence and recovery:
  - `state_store.py`
  - `state_rebuilder.py`
  - `workflow_response.py`
- lifecycle and operator-facing helpers:
  - `ops_tools.py`
  - `test_suggestions.py`
- package metadata / bootstrap:
  - `__init__.py`
  - `init.py`

### Most important design observation

The current implementation already concentrates most protocol behavior into four modules:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`

Those files are the highest-probability edit targets for the `0.6.0` redesign because they currently own:

- transaction ID issuance
- event append validation
- materialized state validation and save
- event-log replay and active transaction reconstruction
- begin / resume / task lifecycle decisions
- verify / commit sequencing
- explicit terminal completion behavior

---

## File-by-file implementation map

Each Python file under `src/` appears once below, per `p0-t01` acceptance criteria.

### `src/agentops_mcp_server/__init__.py`

- **responsibility_summary**: Package marker only. No runtime logic.
- **major_symbols**: none
- **protocol_concerns**:
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: Low. Unlikely to require changes unless packaging metadata changes.

### `src/agentops_mcp_server/commit_manager.py`

- **responsibility_summary**: Owns helper-driven verify-then-commit and direct commit flows. Bridges repo operations with canonical transaction events and state updates.
- **major_symbols**:
  - `CommitManager`
  - `_load_tx_context`
  - `_ensure_tx_begin`
  - `_ensure_verify_started`
  - `_emit_tx_event`
  - `commit_if_verified`
  - `repo_commit`
- **protocol_concerns**:
  - `materialized_state`
  - `event_log`
  - `resume_dispatch`
  - `active_transaction_selection`
  - `verify_flow`
  - `commit_flow`
  - `terminal_completion`
  - `integrity_validation`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: High.
- **why_it_matters**:
  - Reads `active_tx` from `tx_state.json`.
  - Contains bootstrap logic that may emit `tx.begin`.
  - Uses rebuild output as fallback when materialized state is absent.
  - Couples helper behavior to current active transaction identity and phase.
  - Will likely need alignment with the plan’s stricter non-terminal commit semantics and deterministic resume rules.
- **notable current behaviors / risks**:
  - `_load_tx_context` and `_active_tx_from_state` assume integer `tx_id`.
  - `_matching_active_context_from_rebuild` allows matching by either `tx_id` or `ticket_id`, which is a likely mismatch with the exact-identity direction in `0.6.0`.
  - `_ensure_tx_begin` can synthesize bootstrap begin behavior during helper execution.
  - Helper success updates workflow guidance but terminal completion still depends on later lifecycle closure.

### `src/agentops_mcp_server/git_repo.py`

- **responsibility_summary**: Thin wrapper around `git` subprocess calls and diff/status helpers.
- **major_symbols**:
  - `GitRepo`
  - `git`
  - `status_porcelain`
  - `diff_stat`
  - `diff_stat_cached`
- **protocol_concerns**:
  - `tooling_or_helpers`
  - `commit_flow`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Low to medium.
- **why_it_matters**:
  - Used by commit, verify, repo summary, and test suggestion paths.
  - Does not own transaction semantics, but commit flow depends on it.

### `src/agentops_mcp_server/init.py`

- **responsibility_summary**: Bootstraps packaged shell init script execution.
- **major_symbols**:
  - `_script_path`
  - `main`
- **protocol_concerns**:
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: Low.
- **why_it_matters**:
  - Only relevant indirectly because plan text references initialized baseline behavior.

### `src/agentops_mcp_server/json_rpc_server.py`

- **responsibility_summary**: JSON-RPC request loop, request dispatch, and tool failure logging.
- **major_symbols**:
  - `_write_json`
  - `JsonRpcServer`
  - `_log_tool_failure`
  - `handle_request`
  - `run`
- **protocol_concerns**:
  - `tooling_or_helpers`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Medium.
- **why_it_matters**:
  - Central place where failed tool executions are persisted to `.agent/errors.jsonl`.
  - Does not own canonical ordering, but its failure logging supports the persistence/logging requirements.

### `src/agentops_mcp_server/main.py`

- **responsibility_summary**: Top-level dependency wiring and exported tool functions.
- **major_symbols**:
  - singleton wiring for `RepoContext`, `StateStore`, `StateRebuilder`, `VerifyRunner`, `CommitManager`, `RepoTools`, `OpsTools`
  - `workspace_initialize`
  - exported wrappers for all tool handlers
- **protocol_concerns**:
  - `tooling_or_helpers`
  - `materialized_state`
  - `event_log`
- **expected_0_6_0_impact**: Medium.
- **why_it_matters**:
  - Defines startup root binding behavior.
  - Exposes canonical tool surface and wrapper signatures.
  - Type annotations here currently show some mismatches against runtime integer `tx_id` handling elsewhere.

### `src/agentops_mcp_server/ops_tools.py`

- **responsibility_summary**: Main lifecycle orchestration layer for task start/update/end, file intent helpers, state capture, handoff export, task summaries, and session recovery helpers.
- **major_symbols**:
  - `truncate_text`
  - `build_compact_context`
  - `summarize_result`
  - `OpsTools`
  - `_load_tx_state`
  - `_active_tx`
  - `_recover_session_id_from_agent_artifacts`
  - `_resolve_session_id`
  - `_workflow_success_response`
  - `_canonical_begin_conflict`
  - `_emit_tx_event`
  - `_resolve_file_intent_context`
  - `ops_resume_brief`
  - `ops_add_file_intent`
  - `ops_update_file_intent`
  - `ops_complete_file_intent`
  - `ops_start_task`
  - `ops_update_task`
  - `ops_end_task`
  - `ops_capture_state`
  - `ops_task_summary`
  - `ops_observability_summary`
  - `ops_handoff_export`
  - `ops_compact_context`
- **protocol_concerns**:
  - `transaction_identity`
  - `ticket_identity`
  - `task_identity`
  - `session_context`
  - `materialized_state`
  - `event_log`
  - `resume_dispatch`
  - `active_transaction_selection`
  - `status_classification`
  - `next_action_dispatch`
  - `verify_flow`
  - `commit_flow`
  - `terminal_completion`
  - `compatibility`
  - `integrity_validation`
  - `tooling_or_helpers`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Very high.
- **why_it_matters**:
  - Owns begin/resume decision entrypoints used by lifecycle tools.
  - Emits `tx.begin`, `tx.step.enter`, `tx.user_intent.set`, and terminal events.
  - Issues `tx_id` through `_emit_tx_event` on begin.
  - Contains canonical conflict detection for starting a different task while another transaction is active.
  - Contains session recovery from `.agent` artifacts, which is explicitly relevant to the plan’s secondary role for session context.
- **notable current behaviors / risks**:
  - `ops_start_task` requires `task_id` to bootstrap `tx.begin`.
  - `_emit_tx_event` issues a new `tx_id` at `tx.begin` time via `StateStore.issue_tx_id()`.
  - `_resolve_session_id` can recover session identity from multiple `.agent` artifacts; this is broader than the plan’s minimal continuation contract.
  - `ops_end_task` enforces commit completion before `done`.
  - `ops_resume_brief` and capture helpers rely on rebuilt state plus integrity signals.
  - Current code mixes `task_id`, `ticket_id`, and `tx_id` responsibilities in several helper paths, even if partially normalized.

### `src/agentops_mcp_server/repo_context.py`

- **responsibility_summary**: Defines canonical artifact file paths and repo root binding rules.
- **major_symbols**:
  - `CANONICAL_ARTIFACT_FILES`
  - `DERIVED_ARTIFACT_FILES`
  - `RUNTIME_ARTIFACT_FILES`
  - `LEGACY_ARTIFACT_FILES`
  - `STATE_ARTIFACT_FILES`
  - `RepoContext`
  - `bind_repo_root`
  - `state_artifact_path`
  - `legacy_artifact_path`
  - `get_repo_root`
- **protocol_concerns**:
  - `materialized_state`
  - `event_log`
  - `issuance_metadata`
  - `compatibility`
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: Medium.
- **why_it_matters**:
  - Central registry for `.agent/tx_state.json`, `.agent/tx_event_log.jsonl`, `.agent/tx_id_counter.json`, derived files, and legacy journal path.
  - Encodes root initialization rules that align closely with the workspace-binding requirements.

### `src/agentops_mcp_server/repo_tools.py`

- **responsibility_summary**: Repo-facing helpers for verify, status, commit message suggestion, and context capture.
- **major_symbols**:
  - `RepoTools`
  - `_load_tx_context`
  - `_emit_tx_event`
  - `_workflow_guidance`
  - `repo_verify`
  - `repo_status_summary`
  - `repo_commit_message_suggest`
  - `session_capture_context`
- **protocol_concerns**:
  - `materialized_state`
  - `event_log`
  - `verify_flow`
  - `diagnostics_or_guidance`
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: High.
- **why_it_matters**:
  - `repo_verify` emits `tx.verify.start`, `tx.verify.pass`, and `tx.verify.fail`.
  - `_load_tx_context` reads active transaction identity from materialized state.
  - Returns workflow guidance that callers use to decide follow-up actions.
- **notable current behaviors / risks**:
  - `_load_tx_context` currently expects `tx_id` to be a non-empty string, but `state_store.py` and `ops_tools.py` otherwise treat `tx_id` as an integer. This is a concrete identity-boundary inconsistency.
  - Verify behavior falls back to plain verify execution when no tx context is available.

### `src/agentops_mcp_server/state_rebuilder.py`

- **responsibility_summary**: Rebuilds canonical transaction state from the event log, validates event ordering/payloads, and selects the current active transaction.
- **major_symbols**:
  - `StateRebuilder`
  - `resolve_path`
  - `read_tx_event_log`
  - `read_recent_tx_events`
  - `_init_active_tx`
  - `_init_tx_state`
  - `_compute_state_hash`
  - `_validate_tx_event`
  - `_validate_tx_event_payload`
  - `_validate_tx_event_invariants`
  - `_apply_tx_event_to_state`
  - `_derive_next_action`
  - `_tx_state_integrity_ok`
  - `_record_rebuild_drift_error`
  - `rebuild_tx_state`
- **protocol_concerns**:
  - `transaction_identity`
  - `ticket_identity`
  - `session_context`
  - `materialized_state`
  - `event_log`
  - `issuance_metadata`
  - `resume_dispatch`
  - `active_transaction_selection`
  - `status_classification`
  - `next_action_dispatch`
  - `verify_flow`
  - `commit_flow`
  - `terminal_completion`
  - `compatibility`
  - `integrity_validation`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Very high.
- **why_it_matters**:
  - Implements the replay model.
  - Defines bootstrap/default no-history state.
  - Selects active transaction among replay candidates.
  - Detects drift, malformed logs, duplicate begin, and invalid ordering.
  - Derives `next_action` during replay.
- **notable current behaviors / risks**:
  - `_init_tx_state` uses sentinel-style defaults such as `active_tx.tx_id = 0` and `ticket_id = "none"`.
  - Missing event log returns `{ok: False, reason: "tx_event_log missing"}`, while present-but-empty log returns a valid initialized baseline.
  - Replay currently selects active transaction by latest non-terminal candidate, ordered by last event sequence / begin sequence / tx_id.
  - Drift and invalid-history behavior is already present but may need to be bounded and normalized per `0.6.0`.
  - Active transaction reconstruction still depends on stateful candidate selection logic, not only an exact stored active identity.

### `src/agentops_mcp_server/state_store.py`

- **responsibility_summary**: Canonical persistence writer and validator for tx events, tx state, tx_id issuance metadata, and runtime error logs.
- **major_symbols**:
  - constants:
    - `TX_EVENT_TYPES`
    - `FILE_INTENT_OPERATIONS`
    - `FILE_INTENT_STATE_ORDER`
    - `TX_STATUS_VALUES`
    - `VERIFY_STATUS_VALUES`
    - `COMMIT_STATUS_VALUES`
  - helper functions:
    - `now_iso`
    - `_validate_json_int`
    - `canonical_tx_id`
  - `StateStore`
  - `log_tool_error`
  - `read_json_file`
  - `read_tx_id_counter`
  - `write_tx_id_counter`
  - `issue_tx_id`
  - `read_last_json_line`
  - `tx_event_append`
  - `_validate_tx_state`
  - `tx_state_save`
  - `tx_event_append_and_state_save`
- **protocol_concerns**:
  - `transaction_identity`
  - `ticket_identity`
  - `session_context`
  - `materialized_state`
  - `event_log`
  - `issuance_metadata`
  - `status_classification`
  - `next_action_dispatch`
  - `verify_flow`
  - `commit_flow`
  - `terminal_completion`
  - `compatibility`
  - `integrity_validation`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Very high.
- **why_it_matters**:
  - Defines canonical event taxonomy and state validation constraints.
  - Appends canonical events to `.agent/tx_event_log.jsonl`.
  - Saves materialized `.agent/tx_state.json`.
  - Owns issued transaction ID persistence in `.agent/tx_id_counter.json`.
  - Enforces write-order helper `tx_event_append_and_state_save`.
- **notable current behaviors / risks**:
  - `tx_id` is strongly typed as integer here.
  - `_validate_tx_event_invariants` relies on currently materialized `active_tx` and rejects mismatched `tx_id`.
  - `_validate_tx_state` requires always-present `active_tx`, including `next_action`, `semantic_summary`, and `user_intent`.
  - `tx_event_append_and_state_save` mutates semantic fields and next-action routing based on event type.
  - Sentinel no-active values are embedded via conventions such as `tx_id = 0`, `ticket_id = "none"`.

### `src/agentops_mcp_server/test_suggestions.py`

- **responsibility_summary**: Heuristic mapping from changed files or failure logs to likely test targets.
- **major_symbols**:
  - `CODE_SUFFIXES`
  - `unique_preserve_order`
  - `extract_artifact_paths`
  - `is_test_path`
  - `normalize_test_candidate`
  - `candidates_for_path`
  - `parse_changed_files`
  - `TestSuggester`
  - `tests_suggest`
  - `tests_suggest_from_failures`
- **protocol_concerns**:
  - `tooling_or_helpers`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Low.
- **why_it_matters**:
  - Mostly orthogonal to transaction redesign.
  - `extract_artifact_paths` may still be useful in observability or future guidance work.

### `src/agentops_mcp_server/tool_registry.py`

- **responsibility_summary**: Declares tool schemas and binds tool handlers into a registry.
- **major_symbols**:
  - `build_tool_registry`
- **protocol_concerns**:
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: Medium.
- **why_it_matters**:
  - Tool signatures must remain aligned with actual runtime contracts.
  - Currently contains schema declarations whose types do not always perfectly match implementation details elsewhere.

### `src/agentops_mcp_server/tool_router.py`

- **responsibility_summary**: Validates tool invocation arguments, enforces workspace initialization precondition for most file-backed tools, resolves aliases, and formats outputs.
- **major_symbols**:
  - `ToolRouter`
  - `tools_list`
  - `tools_call`
- **protocol_concerns**:
  - `tooling_or_helpers`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: Medium.
- **why_it_matters**:
  - Implements the root-initialization gate.
  - Controls tool accessibility and required argument enforcement.
  - May need schema/runtime alignment cleanup during contract hardening.

### `src/agentops_mcp_server/verify_runner.py`

- **responsibility_summary**: Runs `.zed/scripts/verify` and returns raw result payloads.
- **major_symbols**:
  - `VerifyRunner`
  - `run_verify`
- **protocol_concerns**:
  - `verify_flow`
  - `tooling_or_helpers`
- **expected_0_6_0_impact**: Low to medium.
- **why_it_matters**:
  - Verification execution engine used by repo and commit helpers.
  - Does not itself own transaction ordering.

### `src/agentops_mcp_server/workflow_response.py`

- **responsibility_summary**: Builds machine-readable success/failure responses and derives workflow guidance from active transaction state.
- **major_symbols**:
  - `TERMINAL_STATUSES`
  - `END_TASK_ACTIONS`
  - `DEFAULT_FAILURE_ACTIONS`
  - `derive_workflow_guidance`
  - `build_success_response`
  - `build_failure_response`
  - `build_guidance_from_active_tx`
  - `build_structured_helper_failure`
  - `merge_response_data`
- **protocol_concerns**:
  - `status_classification`
  - `next_action_dispatch`
  - `terminal_completion`
  - `diagnostics_or_guidance`
- **expected_0_6_0_impact**: High.
- **why_it_matters**:
  - Encapsulates canonical status/phase/next-action response semantics.
  - Determines `resume_required`, `can_start_new_ticket`, `requires_followup`, and `followup_tool`.
- **notable current behaviors / risks**:
  - `active_tx_id` is normalized through string-cleaning helpers, which may conflict with integer `tx_id` representation elsewhere.
  - This file is central to separating state classification from dispatch semantics in later tickets.

---

## Concern-to-file matrix

## Transaction identity

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`
- `repo_tools.py`
- `workflow_response.py`

Why:

- issuance, validation, replay, active selection, and response exposure all touch `tx_id`.

## Ticket identity

Primary files:

- `ops_tools.py`
- `state_store.py`
- `state_rebuilder.py`
- `commit_manager.py`
- `repo_tools.py`

Why:

- `ticket_id` is emitted in events, saved in `active_tx`, and used in several fallback or conflict checks.

## Task identity

Primary files:

- `ops_tools.py`
- `workflow_response.py`

Why:

- lifecycle entrypoints take `task_id`, but mapping between `task_id`, `ticket_id`, and `tx_id` is currently mixed.

## Session context

Primary files:

- `ops_tools.py`
- `state_store.py`
- `state_rebuilder.py`
- `commit_manager.py`
- `repo_tools.py`

Why:

- session is stored on events and active state, and can also be heuristically recovered from `.agent` artifacts.

## Materialized state

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`
- `repo_tools.py`
- `repo_context.py`

Why:

- these files read, write, validate, rebuild, or depend directly on `.agent/tx_state.json`.

## Event log

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`
- `repo_tools.py`
- `repo_context.py`

Why:

- these files append events, replay them, or use them as canonical history.

## Issuance metadata

Primary files:

- `state_store.py`
- `repo_context.py`

Why:

- `.agent/tx_id_counter.json` is defined and managed here.

## Resume dispatch

Primary files:

- `ops_tools.py`
- `state_rebuilder.py`
- `workflow_response.py`
- `commit_manager.py`

Why:

- active transaction selection, next-action derivation, and resume guidance are implemented here.

## Active transaction selection

Primary files:

- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`

Why:

- rebuild determines replay winner; lifecycle tools and helpers also resolve or validate against current active tx.

## Status classification

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `workflow_response.py`
- `ops_tools.py`

Why:

- status/phase are validated, replayed, mutated, and exposed as workflow guidance.

## Next-action dispatch

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `workflow_response.py`
- `ops_tools.py`

Why:

- `next_action` is set during append/save, recalculated during rebuild, and surfaced in responses.

## Verify flow

Primary files:

- `repo_tools.py`
- `commit_manager.py`
- `verify_runner.py`
- `state_store.py`
- `state_rebuilder.py`

## Commit flow

Primary files:

- `commit_manager.py`
- `git_repo.py`
- `state_store.py`
- `state_rebuilder.py`
- `workflow_response.py`

## Terminal completion

Primary files:

- `ops_tools.py`
- `state_store.py`
- `state_rebuilder.py`
- `workflow_response.py`
- `commit_manager.py`

## Compatibility and integrity

Primary files:

- `state_rebuilder.py`
- `state_store.py`
- `repo_context.py`
- `ops_tools.py`
- `workflow_response.py`

## Tooling and guidance

Primary files:

- `main.py`
- `tool_registry.py`
- `tool_router.py`
- `json_rpc_server.py`
- `workflow_response.py`

---

## Persistence artifact inventory

This section satisfies the core artifact mapping expected by `p0-t02`.

### Canonical artifacts

#### `.agent/tx_state.json`

- **role**: materialized canonical transaction state
- **defined by**: `repo_context.py`
- **main readers**:
  - `ops_tools.py` via `_load_tx_state`, `_active_tx`, `_materialized_active_tx`
  - `commit_manager.py` via `_load_tx_context`, `_active_tx_from_state`, `_ensure_verify_started`
  - `repo_tools.py` via `_load_tx_context`, `_workflow_guidance`, `repo_verify`
  - `state_store.py` via `_load_active_tx`
  - `state_rebuilder.py` via `rebuild_tx_state` when checking existing materialized state
- **main writers**:
  - `state_store.py` via `tx_state_save`
  - `state_store.py` via `tx_event_append_and_state_save`
  - `ops_tools.py`, `repo_tools.py`, `commit_manager.py` indirectly through `StateStore`
- **validators**:
  - `state_store.py` via `_validate_tx_state`
  - `state_rebuilder.py` via `_tx_state_integrity_ok`
- **rebuild / normalization paths**:
  - `state_rebuilder.py` via `rebuild_tx_state`
  - `ops_tools.py` via `ops_capture_state`
- **current schema assumptions**:
  - `schema_version` must be `0.4.0`
  - `active_tx` is always present
  - `active_tx.tx_id` must be integer
  - `active_tx.ticket_id` must be non-empty string
  - `active_tx.status` and `active_tx.phase` must match
  - `active_tx.next_action` and `semantic_summary` are mandatory
- **0.6.0 alignment notes**:
  - Current model uses always-present sentinel-style `active_tx` baseline instead of purely structural no-active state.
  - Current schema appears broader than the minimal continuation contract described in the plan.

#### `.agent/tx_event_log.jsonl`

- **role**: canonical append-only transaction event history
- **defined by**: `repo_context.py`
- **main readers**:
  - `state_rebuilder.py` via `read_tx_event_log`
  - `state_rebuilder.py` via `read_recent_tx_events`
  - `state_store.py` via `read_last_json_line`
  - `ops_tools.py` session recovery helpers read event log directly
  - `commit_manager.py` checks whether event log is empty
- **main writers**:
  - `state_store.py` via `tx_event_append`
  - `state_store.py` via `tx_event_append_and_state_save`
- **validators**:
  - `state_store.py` validates event append inputs and invariants at write time
  - `state_rebuilder.py` validates shape, payload, and ordering during replay
- **rebuild / normalization paths**:
  - `state_rebuilder.py` via `rebuild_tx_state`
- **current behavior for missing / empty / malformed**:
  - missing file: rebuild returns failure `tx_event_log missing`
  - present but empty file: rebuild returns initialized baseline state
  - malformed lines: counted / skipped in some read paths, but malformed replay records can also lead to drift or invalid-history handling
- **0.6.0 alignment notes**:
  - Missing-vs-empty distinction already exists and is important.
  - Replay and integrity failure paths already exist, but exact bounded compatibility behavior will likely need refinement.

#### `.agent/tx_id_counter.json`

- **role**: issued transaction ID metadata
- **defined by**: `repo_context.py`
- **main readers**:
  - `state_store.py` via `read_tx_id_counter`
- **main writers**:
  - `state_store.py` via `write_tx_id_counter`
  - `state_store.py` via `issue_tx_id`
- **validators**:
  - `state_store.py` enforces integer `last_issued_id` and required `updated_at`
- **rebuild / normalization paths**:
  - none; this is issuance metadata, not replayed transaction history
- **0.6.0 alignment notes**:
  - This file is already the natural anchor for issued `tx_id` semantics and will be central to `p2-t01`.

### Derived artifacts

#### `.agent/handoff.json`

- **role**: derived handoff summary
- **defined by**: `repo_context.py`
- **main readers**:
  - `ops_tools.py` handoff / resume related helpers
- **main writers**:
  - `ops_tools.py` via `ops_handoff_export`
- **0.6.0 alignment notes**:
  - Derived-only role matches the plan/rules direction.

#### `.agent/observability_summary.json`

- **role**: derived observability summary
- **defined by**: `repo_context.py`
- **main readers**:
  - no major canonical runtime dependence found
- **main writers**:
  - `ops_tools.py` via `ops_observability_summary`

### Runtime support artifacts

#### `.agent/errors.jsonl`

- **role**: runtime tool failure log
- **defined by**: `repo_context.py`
- **main readers**:
  - `ops_tools.py` may use it indirectly during session recovery scans
- **main writers**:
  - `state_store.py` via `log_tool_error`
  - `json_rpc_server.py` via `_log_tool_failure`
- **0.6.0 alignment notes**:
  - Supports the persistence/logging requirement for failed tool executions.

### Legacy artifacts

#### `.agent/journal.jsonl`

- **role**: legacy artifact path only
- **defined by**: `repo_context.py`
- **main readers/writers found**:
  - no major active runtime ownership surfaced in the current survey
- **0.6.0 alignment notes**:
  - Relevant as compatibility context, but not a current canonical driver.

### Other `.agent` files observed in code

These are not part of the core canonical artifact set, but they affect runtime behavior:

#### `.agent/debug_start_time.json`

- **role**: session-recovery filter anchor
- **used by**:
  - `ops_tools.py` via `_debug_start_time`
  - `_recover_session_id_from_agent_artifacts`
- **importance**:
  - Influences session ID recovery heuristics.
  - Relevant to the plan’s effort to narrow the correctness boundary away from optional metadata.

---

## Read/write code-path map

## `.agent/tx_state.json`

### Read paths

- `ops_tools.py`
  - `_load_tx_state`
  - `_materialized_active_tx`
- `commit_manager.py`
  - `_load_tx_context`
  - `_active_tx_from_state`
  - `_ensure_verify_started`
  - `_emit_tx_event`
- `repo_tools.py`
  - `_load_tx_context`
  - `_workflow_guidance`
  - `repo_verify`
- `state_store.py`
  - `_load_active_tx`
- `state_rebuilder.py`
  - `rebuild_tx_state`

### Write paths

- `state_store.py`
  - `tx_state_save`
  - `tx_event_append_and_state_save`
- indirect writers through `StateStore`:
  - `ops_tools.py`
  - `repo_tools.py`
  - `commit_manager.py`

## `.agent/tx_event_log.jsonl`

### Read paths

- `state_store.py`
  - `read_last_json_line`
- `state_rebuilder.py`
  - `read_tx_event_log`
  - `read_recent_tx_events`
  - `rebuild_tx_state`
- `ops_tools.py`
  - `_recover_session_id_from_agent_artifacts`
- `commit_manager.py`
  - `_event_log_empty`

### Write paths

- `state_store.py`
  - `tx_event_append`
  - `tx_event_append_and_state_save`

## `.agent/tx_id_counter.json`

### Read paths

- `state_store.py`
  - `read_tx_id_counter`

### Write paths

- `state_store.py`
  - `write_tx_id_counter`
  - `issue_tx_id`

## `.agent/errors.jsonl`

### Read paths

- no primary canonical read path; optionally scanned by `ops_tools.py` during session recovery

### Write paths

- `state_store.py`
  - `log_tool_error`
- `json_rpc_server.py`
  - `_log_tool_failure` delegates to `StateStore`

## `.agent/handoff.json`

### Read paths

- `ops_tools.py` related handoff usage

### Write paths

- `ops_tools.py`
  - `ops_handoff_export`

## `.agent/observability_summary.json`

### Write paths

- `ops_tools.py`
  - `ops_observability_summary`

---

## Begin, resume, and active-transaction selection map

This section satisfies the code-path mapping expected by `p0-t03`.

## Begin entrypoints

### Primary begin path: `OpsTools.ops_start_task`

Current behavior:

1. Validates `title`
2. Normalizes requested `task_id`
3. Checks current active transaction state via `_active_tx`
4. If no active non-terminal transaction exists:
   - requires `task_id`
   - runs `_canonical_begin_conflict`
   - emits `tx.begin` through `_emit_tx_event`
   - `_emit_tx_event` issues a fresh `tx_id` using `StateStore.issue_tx_id()`
5. Emits `tx.step.enter` for the task step

Why this is the main begin path:

- It is the clearest explicit lifecycle entrypoint for canonical work start.

### Secondary helper bootstrap begin path: `CommitManager._ensure_tx_begin`

Current behavior:

- Loads tx context from materialized state.
- If event log is empty, it may emit `tx.begin` or materialize rebuilt state.
- Used to bootstrap helper-driven flows such as `commit_if_verified`.

Risk:

- This means begin behavior is not exclusively owned by lifecycle start.
- Later tickets should consider whether helper bootstrap is compatible with the stricter canonical ordering model.

## Resume / active transaction lookup paths

### `OpsTools._require_active_tx` and related helpers

Role:

- Resolve the currently active transaction and optionally enforce requested task matching.

Why important:

- This is likely the main lifecycle-layer resume gate.

### `OpsTools._load_tx_state` and `_active_tx`

Role:

- Load materialized state, or fallback to rebuild if materialized state is missing and integrity is healthy.

Risk:

- Resume may depend on rebuilt or recovered state, not only materialized state.
- That is relevant to deterministic resume requirements.

### `CommitManager._load_tx_context`

Role:

- Reads `active_tx` from materialized state and returns helper context.

Risk:

- Assumes integer `tx_id`.
- Helper flow may proceed from materialized state independently of lifecycle start/update tools.

### `RepoTools._load_tx_context`

Role:

- Reads active transaction context for verify flow.

Risk:

- Expects string `tx_id`, unlike other core files.
- This inconsistency is important for later identity tickets.

## Active transaction selection during replay

### `StateRebuilder.rebuild_tx_state`

This is the core replay-based selection path.

Current selection behavior:

- Replays all valid events.
- Builds per-transaction replay state.
- Marks terminal transactions.
- Builds a candidate list of non-terminal transactions.
- Picks the selected active transaction by maximum:
  - last event sequence
  - begin sequence
  - tx_id

Implications:

- Selection is heuristic / computed from replay ordering.
- It is not purely “resume exactly the known active_tx identity” in the stricter sense described by the plan.
- This file is therefore central to `p2-t02`, `p2-t03`, `p2-t05`, and `p2-t06`.

## No-active representation

Current behavior:

- `StateRebuilder._init_tx_state()` creates sentinel-like baseline:
  - `active_tx.tx_id = 0`
  - `active_tx.ticket_id = "none"`
  - `status = "planned"`
  - `phase = "planned"`

Implications:

- No-active state is represented by a structural object with sentinel values, not absence.
- This directly conflicts with the plan’s “sentinel elimination” direction and makes `state_rebuilder.py` plus `state_store.py` primary targets for `p2-t03`.

## Session-driven or artifact-driven recovery influences

### `OpsTools._recover_session_id_from_agent_artifacts`

Current behavior:

- Searches `.agent` artifacts for candidate `session_id` values.
- Uses `debug_start_time.json` as a filter.
- Prefers matching event-log records for active tx.
- Falls back to other `.agent` files.

Implications:

- Session context currently influences continuation.
- This is broader than the minimal canonical continuation contract.
- Relevant future target for `p2-t07`.

## Workflow guidance and resume advice

### `workflow_response.py`

Role:

- Converts current active transaction state into machine-readable:
  - `canonical_status`
  - `canonical_phase`
  - `next_action`
  - `requires_followup`
  - `followup_tool`
  - `can_start_new_ticket`
  - `resume_required`

Why important:

- Even when selection happens elsewhere, actual dispatch guidance is centralized here.
- This file will be important for separating status classification from dispatch semantics.

---

## Current schema and defaulting notes

## Event schema

Write-time enforced in `state_store.py`:

Required fields:

- `seq`
- `event_id`
- `ts`
- `project_root`
- `tx_id`
- `ticket_id`
- `event_type`
- `phase`
- `step_id`
- `actor`
- `session_id`
- `payload`

Important constraints:

- `tx_id` must be integer
- `event_type` must be in `TX_EVENT_TYPES`
- payload validation depends on event type
- ordering/invariant validation consults current active state

## Materialized state schema

Write-time enforced in `state_store.py`:

Top-level required fields:

- `schema_version == "0.4.0"`
- `active_tx`
- `last_applied_seq`
- `updated_at`
- `integrity`

`active_tx` required fields include:

- `tx_id`
- `ticket_id`
- `status`
- `phase`
- `current_step`
- `next_action`
- `file_intents`
- `semantic_summary`
- `user_intent`
- `verify_state`
- `commit_state`

Important defaults during rebuild:

- sentinel active tx object always exists
- verify/commit state default to `not_started`
- `next_action` is derived during replay or initialized on baseline state

## Issuance metadata schema

In `state_store.py`:

- `last_issued_id`: integer
- `updated_at`: non-empty string

Missing file default:

- returns logical baseline with `last_issued_id = 0`

---

## Mismatches and risks relative to the 0.6.0 plan

These are descriptive alignment notes for later tickets.

### 1. Identity typing is inconsistent across files

Observed inconsistency:

- `state_store.py`, `state_rebuilder.py`, `ops_tools.py`, and `commit_manager.py` mostly treat `tx_id` as integer.
- `repo_tools.py` and parts of `workflow_response.py` normalize transaction identity as strings.

Impact:

- High risk for identity-boundary bugs.
- Primary target area for `p1-t01`.

### 2. No-active state uses sentinel values

Observed behavior:

- replay baseline and active state defaults use `tx_id = 0` and `ticket_id = "none"`.

Impact:

- Directly relevant to `p2-t03`.
- Makes state validity depend on sentinel conventions.

### 3. Active transaction selection is replay-derived and heuristic

Observed behavior:

- `StateRebuilder.rebuild_tx_state()` selects the latest non-terminal candidate by ordering rules.

Impact:

- May conflict with the plan’s goal of exact active transaction continuation.
- Primary target for `p2-t02`.

### 4. Resume uses broader context than the minimal continuation contract

Observed behavior:

- `ops_tools.py` can recover session IDs from multiple `.agent` artifacts.
- helper logic can fall back from materialized state to rebuild state.

Impact:

- Useful operationally, but broader than the plan’s “minimal canonical continuation fields” approach.
- Relevant to `p1-t02` and `p2-t07`.

### 5. Begin can be synthesized from helper paths

Observed behavior:

- `CommitManager._ensure_tx_begin()` can bootstrap a begin event.

Impact:

- Begin ownership is not isolated to lifecycle start.
- Relevant to `p0-t03`, `p1-t04`, and possibly `p2-t05`.

### 6. State schema is broader than the minimal continuation contract

Observed behavior:

- `tx_state_save` requires fields such as `semantic_summary`, `next_action`, `verify_state`, `commit_state`, and `file_intents` at all times.

Impact:

- The saved schema may be more coupled than the `0.6.0` plan intends.
- Relevant to `p1-t02` and `p2-t04`.

### 7. Workflow guidance and canonical dispatch are only partially separated

Observed behavior:

- `next_action` is produced in state mutation logic, replay logic, and response logic.
- Classification and dispatch semantics are spread across `state_store.py`, `state_rebuilder.py`, and `workflow_response.py`.

Impact:

- Relevant to `p1-t03` and `p2-t05`.

### 8. Missing event log and empty event log already differ

Observed behavior:

- missing `.agent/tx_event_log.jsonl` is an error
- present-but-empty log is a valid baseline

Impact:

- This aligns well with the stricter rules and should be preserved intentionally.
- Relevant to `p2-t08`.

---

## High-impact file shortlist

These are the strongest expected edit targets for later implementation tickets.

### Tier 1: almost certainly modified

- `src/agentops_mcp_server/state_store.py`
- `src/agentops_mcp_server/state_rebuilder.py`
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/workflow_response.py`

Reasons:

- own canonical identity, persistence, replay, active transaction selection, no-active representation, lifecycle routing, and workflow guidance

### Tier 2: very likely modified

- `src/agentops_mcp_server/commit_manager.py`
- `src/agentops_mcp_server/repo_tools.py`
- `src/agentops_mcp_server/repo_context.py`

Reasons:

- helper ordering, verify/commit emission, tx context loading, artifact definition, and contract alignment

### Tier 3: may need contract or wiring cleanup

- `src/agentops_mcp_server/main.py`
- `src/agentops_mcp_server/tool_registry.py`
- `src/agentops_mcp_server/tool_router.py`

Reasons:

- tool schemas, exported signatures, initialization gates, and surface-level contract consistency

### Tier 4: likely unaffected or lightly affected

- `src/agentops_mcp_server/git_repo.py`
- `src/agentops_mcp_server/verify_runner.py`
- `src/agentops_mcp_server/test_suggestions.py`
- `src/agentops_mcp_server/json_rpc_server.py`
- `src/agentops_mcp_server/init.py`
- `src/agentops_mcp_server/__init__.py`

---

## Ticket-to-file impact map

## `p1-t01` Define and enforce identity boundary

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `repo_tools.py`
- `workflow_response.py`
- `commit_manager.py`

## `p1-t02` Define minimal canonical continuation contract

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `workflow_response.py`

## `p1-t03` Separate status classification from next_action dispatch

Primary files:

- `workflow_response.py`
- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`

## `p1-t04` Align checkpoint events with canonical core event set

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`
- `repo_tools.py`

## `p2-t01` Replace ticket-derived tx_id generation with issued tx IDs

Primary files:

- `state_store.py`
- `ops_tools.py`
- `commit_manager.py`
- `repo_tools.py`

Note:

- issuance metadata already exists, so this should extend an existing mechanism rather than invent a new one.

## `p2-t02` Unify active transaction selection around exact active_tx identity

Primary files:

- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`

## `p2-t03` Remove sentinel active-transaction semantics

Primary files:

- `state_rebuilder.py`
- `state_store.py`
- `workflow_response.py`
- `ops_tools.py`

## `p2-t04` Align materialized state with minimal continuation contract

Primary files:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`

## `p2-t05` Make canonical next_action the sole continuation dispatcher

Primary files:

- `workflow_response.py`
- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `commit_manager.py`

## `p2-t06` Normalize post-terminal handling into canonical no-active baseline

Primary files:

- `ops_tools.py`
- `state_rebuilder.py`
- `state_store.py`
- `workflow_response.py`

## `p2-t07` Bound session context to a secondary runtime role

Primary files:

- `ops_tools.py`
- `state_rebuilder.py`
- `state_store.py`

## `p2-t08` Bounded historical compatibility and malformed persistence behavior

Primary files:

- `state_rebuilder.py`
- `state_store.py`
- `repo_context.py`
- `workflow_response.py`

## `p3-*` regression coverage and guidance

Expected code targets plus tests/docs around:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `workflow_response.py`
- `commit_manager.py`
- `repo_tools.py`

---

## Recommended downstream editing order

A practical order, based on the current map:

1. normalize identity model and type consistency
2. narrow the canonical continuation contract
3. separate status reporting from dispatch semantics
4. simplify active transaction and no-active representation
5. update helper flows to obey the new canonical dispatcher
6. harden malformed / historical compatibility behavior
7. add interruption-focused regression coverage
8. update operator guidance and docs

---

## Summary

Phase 0 shows that the `0.6.0` redesign is concentrated in a small core:

- `state_store.py`
- `state_rebuilder.py`
- `ops_tools.py`
- `workflow_response.py`

The most important current implementation characteristics are:

- issued transaction ID persistence already exists
- active transaction reconstruction is replay-based and heuristic
- no-active state is sentinel-based
- session recovery currently reaches beyond the minimal canonical contract
- status and next-action semantics are distributed across multiple modules
- helper begin / verify / commit flows are partially autonomous

That makes phase 0 successful as a codebase map: later tickets can now choose exact edit targets without repeating repository-wide discovery.