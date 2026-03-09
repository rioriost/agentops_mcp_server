from __future__ import annotations

from textwrap import dedent

CANONICAL_WORKFLOW_RULES = (
    dedent(
        """\
    # AgentOps (strict rules)
    # Goal: Maximize resumability and stable execution under session interruption.

    ## Start (mandatory)
    - Before any canonical restore or file-backed tool execution, call `workspace_initialize(cwd)` exactly once for the current project directory.
    - `workspace_initialize(cwd)` rules:
      - `cwd` must be the project directory for this MCP server session
      - `cwd` must not be `/`
      - same-root reinitialization is allowed as a no-op
      - rebinding to a different root is invalid
    - Read/restore in this order after successful workspace initialization:
      1) tx_state (materialized transaction state)
      2) tx_event_log (transaction event log replay if needed)
      3) handoff (derived-only, never canonical)
    - Resume decisions must use canonical tx_state + tx_event_log only; handoff is derived.
    - Treat `.agent/handoff.json` as derived-only.
    - Canonical transaction log handling:
      - missing `.agent/tx_event_log.jsonl` means the workspace is uninitialized or damaged
      - present-but-empty `.agent/tx_event_log.jsonl` is a valid initialized zero-event baseline equivalent to `zed-agentops-init.sh`
      - malformed or non-parseable log content remains a strict replay/integrity failure and must not be treated like an empty log
    - If resume state is incomplete:
      - run ops_resume_brief (or equivalent) and emit a short brief
    - If `active_tx.status` is not `done` or `blocked`, resume that active transaction first.
    - Do not start a new ticket while a non-terminal active transaction exists.
    - Select the next executable ticket only when there is no active transaction to resume.
    - Identify active ticket (status != done) and resume it.
    - Root-dependent tools must not run before workspace initialization completes successfully.

    ## Planning flow (convention)
    - User may provide docs/draft.md to guide ticket-oriented execution.
    - Clients may maintain docs/__version__/plan.md with phases.
    - Clients may also maintain derived planning artifacts such as:
      - docs/__version__/tickets_list.json (metadata)
      - docs/__version__/pX-tY.json (full ticket with status/inputs/outputs/deps)
    - Suggested ticket status enum for client-managed artifacts: planned, in-progress, checking, verified, committed, done, blocked.
    - Ticket artifacts are client-managed workflow convention, not mandatory server protocol.
    - MCP clients must not assume the server generates, persists, synchronizes, or validates:
      - docs/__version__/plan.md
      - docs/__version__/tickets_list.json
      - docs/__version__/pX-tY.json
    - If a client chooses to maintain ticket artifacts, keeping per-ticket JSON and docs/__version__/tickets_list.json synchronized is recommended operating practice.

    ## Work loop (mandatory)
    - Tickets are the only unit of work.
    - Canonical ordering is strict:
      - `tx.begin` before task lifecycle events
      - `tx.verify.start` before `tx.verify.pass` or `tx.verify.fail`
      - `tx.verify.pass` before `tx.file_intent.update` with `state=verified`
      - file intent updates require a previously registered file intent for the same path
      - commit operations require a valid verify sequence and existing transaction context
    - For any code change:
      1) Set runtime work status -> in-progress (emit tx.begin if new)
         - If a client maintains ticket artifacts, it may also persist the matching ticket status in its own planning files when work begins.
      2) Register file intents before mutation
      3) Implement smallest safe change
      4) Update semantic_summary (required) and user_intent only on explicit user resume intent; persist tx_state after mutation
      5) Run `repo_verify` (runs `.zed/scripts/verify`)
         - If fails: fix and repeat (update semantic summary)
      6) Set runtime work status -> checking
         - If a client maintains ticket artifacts, it may also update them.
         - Compare acceptance_criteria AND plan.md when those planning artifacts are being used by the client workflow
      7) Set runtime work status -> verified
         - If a client maintains ticket artifacts, it may also update them.
      8) Commit changes (emit tx.commit.start/done|fail)
         - `commit_if_verified` and `repo_commit` may complete the repository commit while leaving the active transaction in canonical `committed`.
         - Successful commit helper completion does not by itself imply terminal success.
      9) Set runtime work status -> committed
         - `committed` is a non-terminal state.
         - If canonical `next_action` is `tx.end.done`, the active transaction must still be closed explicitly.
         - If a client maintains ticket artifacts, it may also update them.
      10) Set runtime work status -> done (emit tx.end.done|blocked)
         - Terminal success requires explicit lifecycle completion, typically `ops_end_task(status="done")`.
         - A transaction remains active until status/phase becomes `done` or `blocked`.
         - If a client maintains ticket artifacts, it may also persist terminal status there.
    - Runtime transaction status/phase is canonical for server behavior.
    - Agents must use canonical transaction status/phase and `next_action` to determine whether follow-up lifecycle completion is still required after verify or commit helpers succeed.
    - Lifecycle-aware success responses should be treated as machine-readable workflow guidance, not prose-only hints.
    - When present, agents should branch primarily on fields such as:
      - `canonical_status`
      - `canonical_phase`
      - `next_action`
      - `terminal`
      - `requires_followup`
      - `followup_tool`
      - `active_tx_id`
      - `active_ticket_id`
    - Lifecycle- and state-related failure responses should remain machine-distinguishable when possible.
    - When present, agents should use fields such as:
      - `error_code`
      - `reason`
      - `recoverable`
      - `recommended_next_tool`
      - `recommended_action`
      - `integrity_status`
      - `blocked`
    - Helper success does not by itself imply terminal completion; non-terminal `committed` must remain distinguishable from terminal `done` and `blocked`.
    - Client ticket-document status, when maintained, is derived workflow bookkeeping and may be synchronized by the client as a convention.

    ## Persistence & logging (mandatory)
    - Always record events for plan/task/progress/verify/commit.
    - Canonical write ordering: event append → tx_state update → cursor persist.
    - semantic_summary is required for non-terminal tx; user_intent is only set on explicit user resume intent.
    - Keep log outputs short (summaries over full diffs).
    - Prefer diff stats over full diffs.
    - Failed tool executions should be persisted to `.agent/errors.jsonl` when runtime support is available.
    - Error records should include at least:
      - tool name
      - tool input
      - tool output or error
      - timestamp

    ## Handoff & session safety (mandatory)
    - When a tool execution adds/modifies files:
      1) ops_compact_context (compact context)
      2) ops_capture_state (tx_state capture)
      3) ops_handoff_export (handoff summary)

    ## Tooling (mandatory)
    - Prefer MCP tools if available.
    - Required input contracts:
      - `workspace_initialize`
        - `cwd` is required and must be a project directory path
        - `cwd` must not be `/`
      - `tx_event_append`
        - `actor` is required and must be an object
        - `payload` is required and must be an object
        - `session_id` is required and must be non-empty
      - `tx_state_save`
        - `state` is required and must be a valid transaction state object
        - do not persist incomplete or invalid transaction snapshots
      - task lifecycle tools
        - do not call task start/update/end before `tx.begin`
        - `session_id` is required and must be non-empty when the lifecycle tool contract requires it
        - preserve or recover the canonical active transaction session context before attempting lifecycle continuation
      - time lookup
        - supported `timezone` values are `utc` or `local` only
    - Prefer MCP tools if available.
    - Use:
      - workspace_initialize
      - commit_if_verified
        - commit helper only; may leave the transaction in non-terminal `committed`
        - follow canonical `next_action` after success; if it is `tx.end.done`, explicitly close the lifecycle
      - tx_event_append
      - tx_state_save
      - tx_state_rebuild
      - repo_verify
        - use returned canonical workflow guidance and persisted transaction state to determine whether the next step is commit or repair/retry
      - repo_commit
        - commit helper only; may leave the transaction in non-terminal `committed`
        - follow canonical `next_action` after success; if it is `tx.end.done`, explicitly close the lifecycle
      - repo_status_summary
      - repo_commit_message_suggest
      - session_capture_context
      - tests_suggest
      - tests_suggest_from_failures
      - ops_compact_context
      - ops_handoff_export
      - ops_resume_brief
      - ops_start_task
      - ops_update_task
      - ops_end_task
        - use for explicit terminal lifecycle completion such as `ops_end_task(status="done")`
      - ops_capture_state
      - ops_task_summary
      - ops_observability_summary

    ## Commit rules (mandatory)
    - After verify: check repo status; commit only if changes exist.
    - Successful commit helpers may advance canonical transaction state only to `committed`; they do not by themselves imply terminal success.
    - If post-commit canonical `next_action` is `tx.end.done`, explicitly complete the lifecycle with terminal success handling, typically `ops_end_task(status="done")`.
    - Commit message: ~80 chars, add scope if useful.

    ## Token discipline (mandatory)
    - Keep outputs short; avoid large logs.
    - Prefer summaries and diff stats.
    """
    ).strip()
    + "\n"
)


def canonical_workflow_rules() -> str:
    return CANONICAL_WORKFLOW_RULES
