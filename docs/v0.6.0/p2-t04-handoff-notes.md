# p2-t04 handoff notes: repo tools and bounded session compatibility follow-up

## Context

`p2-t03` was intentionally kept narrow:

- do not modify `src/`
- adjust `tests/test_commit_manager.py` expectations to match the current implementation
- verify only the work needed to unblock the `commit_manager`-scoped ticket

That work is now in a good stopping state for the `commit_manager` area:

- `tests/test_commit_manager.py` passes locally
- result observed: `74 passed`

The remaining follow-up is not `commit_manager`-scoped anymore. It has shifted into `repo_tools` / `ops_tools` behavior and their associated tests, which fits better under `p2-t04`.

## Why this handoff belongs to p2-t04

The remaining failures are centered on behavior tied to:

- bounded use of `session_id`
- canonical vs helper-facing transaction identity
- exact active transaction enforcement
- compatibility treatment for historical values like `"none"`
- helper guidance fields emitted by `repo_verify()`
- terminal transaction behavior in repo/ops helper flows

Those concerns map more naturally to:

- `docs/v0.6.0/p2-t04.json`
- `REQ-P2-SESSION-COMPAT`

rather than to `p2-t03`, which was focused on exact-active-transaction resume simplification.

## Local test status at handoff

### Commit-manager-only verification
The following passed:

- `tests/test_commit_manager.py`

Observed result:

- `74 passed`

### Repo-tools-adjacent verification
Running the test files associated with currently modified `src/` modules surfaced remaining failures in:

- `tests/test_repo_tools.py`

The grouped run used was effectively:

- `tests/test_commit_manager.py`
- `tests/test_json_rpc_server.py`
- `tests/test_repo_tools.py`
- `tests/test_tool_router.py`

and the visible failures were concentrated in `tests/test_repo_tools.py`.

## Remaining failing themes

### 1. `repo_verify()` helper guidance does not match current test expectations

Several tests expect `repo_verify()` to return post-verify canonical guidance such as:

- success => `canonical_status == "verified"`
- failure => `canonical_status == "checking"`

But the observed results preserve earlier top-level status values such as:

- `"checking"`
- `"in-progress"`

Relevant failing tests included:

- `test_repo_verify_success_guidance_is_internally_consistent`
- `test_repo_verify_with_active_tx_exposes_helper_guidance`
- `test_repo_verify_failed_result_preserves_helper_guidance`
- `test_repo_verify_records_failure_event_when_verify_fails`

### 2. Terminal transaction verify behavior differs from expectation

A test expected terminal transactions to be rejected with an exception, but the current implementation did not raise.

Relevant failing test:

- `test_repo_verify_rejects_terminal_transaction`

### 3. Historical compatibility for `" none "` differs from expectation

`OpsTools._normalize_tx_identifier(" none ")` currently appears to normalize to `"none"` rather than the empty string.

Relevant failing test:

- `test_ops_tools_helper_branches_cover_identifier_and_error_helpers`

This is exactly the kind of bounded historical compatibility question `p2-t04` should decide explicitly.

### 4. `allow_resume=True` still does not permit ticket-id-based matching in `_require_active_tx`

A test expected:

- `_require_active_tx("p1-t1", allow_resume=True)`

to succeed against the active transaction, but the current implementation still rejects it because canonical matching is based on canonical transaction identity rather than ticket label.

Relevant failing test:

- `test_ops_tools_require_active_tx_allow_resume_and_terminal_detection`

This is also strongly aligned with `p2-t04` because it touches the rule that helper inputs must not be promoted into canonical runtime identity.

## Source files likely in scope for p2-t04

These are the most likely runtime files to inspect first:

- `src/agentops_mcp_server/repo_tools.py`
- `src/agentops_mcp_server/ops_tools.py`
- `src/agentops_mcp_server/workflow_response.py`

Potentially also, depending on how guidance is derived:

- `src/agentops_mcp_server/tool_router.py`
- `src/agentops_mcp_server/json_rpc_server.py`

## Test files likely in scope for p2-t04

Primary:

- `tests/test_repo_tools.py`

Secondary if behavior cascades:

- `tests/test_tool_router.py`
- `tests/test_json_rpc_server.py`

## Recommended starting point for p2-t04

1. Read `docs/v0.6.0/p2-t04.json` again and treat it as the scope boundary.
2. Decide explicitly, before editing code or tests:
   - whether `"none"` is a bounded historical identifier that remains readable
   - whether helper-facing resume inputs may match by ticket label, or only by canonical tx identity
   - whether `repo_verify()` should expose pre-event or post-event canonical guidance
   - whether terminal transactions should hard-fail in `repo_verify()` or degrade to a non-mutating verify path
3. Audit `tests/test_repo_tools.py` and classify each failure as one of:
   - expectation should move toward current implementation
   - implementation should move toward p2-t04 plan semantics
4. Keep `src/` changes tightly limited to `repo_tools` / `ops_tools` semantics if code changes are required.
5. Re-run only the repo-tools-adjacent tests until stable, then broaden if needed.

## Strong caution

Do not accidentally pull `p2-t04` back into a broad protocol rewrite.

The useful boundary discovered during `p2-t03` is:

- `commit_manager` expectations can be aligned in tests-only mode
- the remaining disputed behavior is now about canonical identity, helper guidance, and bounded compatibility
- that is a separate design/implementation decision surface and should stay isolated

## Suggested inputs to add to `p2-t04.json`

Add this file to `inputs`:

- `docs/v0.6.0/p2-t04-handoff-notes.md`

Optionally also consider adding the directly implicated test file if your ticket format allows test artifacts as inputs:

- `tests/test_repo_tools.py`

## Suggested p2-t04 objective refinement

If you want a sharper execution target, phrase the immediate objective for `p2-t04` as:

> Resolve bounded session/history compatibility and helper-guidance behavior in `repo_tools` / `ops_tools` without promoting helper-provided identifiers into canonical transaction identity.

## Minimal next action

Start with the failures in `tests/test_repo_tools.py`, especially:

- `repo_verify()` guidance expectations
- `_normalize_tx_identifier(" none ")`
- `_require_active_tx(..., allow_resume=True)`
- terminal verify behavior

Those four areas appear to define the real p2-t04 decision surface.