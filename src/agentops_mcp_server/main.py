#!/usr/bin/env python3
"""
Minimal MCP-like stdio server.

This implements a tiny JSON-RPC 2.0 protocol over stdin/stdout to expose tools.
It is intentionally lightweight and dependency-free so you can adapt it to your
preferred MCP client integration.

Supported methods:
- tools/list -> returns tool schemas
- tools/call -> invokes a tool by name with arguments

Tools (snake_case):
- commit_if_verified(message, timeout_sec?) -> run verify and commit changes
- journal_append(kind, payload, session_id?, agent_id?, event_id?) -> append event
- snapshot_save(state, session_id?, last_applied_seq?, snapshot_id?) -> save snapshot
- snapshot_load() -> load snapshot
- checkpoint_update(last_applied_seq, snapshot_path?, checkpoint_id?) -> update checkpoint
- checkpoint_read() -> read checkpoint
- roll_forward_replay(checkpoint_path?, snapshot_path?, start_seq?, end_seq?) -> replay journal
- continue_state_rebuild(checkpoint_path?, snapshot_path?, start_seq?, end_seq?, session_id?) -> rebuild state
- repo_verify(timeout_sec?) -> run verify script
- repo_commit(message?, files="auto") -> commit changes
- repo_status_summary() -> summarize repo status and diff
- repo_commit_message_suggest(diff?) -> suggest commit messages
- session_capture_context(run_verify?, log?) -> capture repo context
- tests_suggest(diff?, failures?) -> suggest tests
- tests_suggest_from_failures(log_path) -> suggest tests from failure logs
- ops_compact_context(max_chars?, include_diff?) -> generate compact context
- ops_handoff_export() -> export handoff JSON
- ops_resume_brief(max_chars?) -> generate resume brief
- ops_start_task(title, task_id?, session_id?, agent_id?, status?) -> record task start
- ops_update_task(status?, note?, task_id?, session_id?, agent_id?) -> record task update
- ops_end_task(summary, next_action?, status?, task_id?, session_id?, agent_id?) -> record task end
- ops_capture_state(session_id?) -> snapshot and checkpoint state
- ops_task_summary(session_id?, max_chars?) -> summarize task state
- ops_observability_summary(session_id?, max_events?, max_chars?) -> write observability summary
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .commit_manager import CommitManager
from .git_repo import GitRepo
from .json_rpc_server import JsonRpcServer
from .ops_tools import OpsTools
from .repo_context import RepoContext
from .repo_tools import RepoTools
from .state_rebuilder import StateRebuilder
from .state_store import StateStore
from .test_suggestions import TestSuggester
from .tool_registry import build_tool_registry
from .tool_router import ToolRouter
from .verify_runner import VerifyRunner

_REPO_CONTEXT = RepoContext(Path.cwd().resolve())
_STATE_STORE = StateStore(_REPO_CONTEXT)
_STATE_REBUILDER = StateRebuilder(_REPO_CONTEXT, _STATE_STORE)
_GIT_REPO = GitRepo(_REPO_CONTEXT)
_VERIFY_RUNNER = VerifyRunner(_REPO_CONTEXT, _STATE_STORE)
_COMMIT_MANAGER = CommitManager(
    _GIT_REPO, _VERIFY_RUNNER, _STATE_STORE, _STATE_REBUILDER
)
_REPO_TOOLS = RepoTools(_GIT_REPO, _VERIFY_RUNNER)
_TEST_SUGGESTER = TestSuggester(_GIT_REPO, _REPO_CONTEXT)
_OPS_TOOLS = OpsTools(_REPO_CONTEXT, _STATE_STORE, _STATE_REBUILDER, _GIT_REPO)

TOOL_REGISTRY = build_tool_registry(
    commit_if_verified=_COMMIT_MANAGER.commit_if_verified,
    journal_append=_STATE_STORE.journal_append,
    snapshot_save=_STATE_STORE.snapshot_save,
    snapshot_load=_STATE_STORE.snapshot_load,
    checkpoint_update=_STATE_STORE.checkpoint_update,
    checkpoint_read=_STATE_STORE.checkpoint_read,
    roll_forward_replay=_STATE_REBUILDER.roll_forward_replay,
    continue_state_rebuild=_STATE_REBUILDER.continue_state_rebuild,
    repo_verify=_REPO_TOOLS.repo_verify,
    repo_commit=_COMMIT_MANAGER.repo_commit,
    repo_status_summary=_REPO_TOOLS.repo_status_summary,
    repo_commit_message_suggest=_REPO_TOOLS.repo_commit_message_suggest,
    session_capture_context=_REPO_TOOLS.session_capture_context,
    tests_suggest=_TEST_SUGGESTER.tests_suggest,
    tests_suggest_from_failures=_TEST_SUGGESTER.tests_suggest_from_failures,
    ops_compact_context=_OPS_TOOLS.ops_compact_context,
    ops_handoff_export=_OPS_TOOLS.ops_handoff_export,
    ops_resume_brief=_OPS_TOOLS.ops_resume_brief,
    ops_start_task=_OPS_TOOLS.ops_start_task,
    ops_update_task=_OPS_TOOLS.ops_update_task,
    ops_end_task=_OPS_TOOLS.ops_end_task,
    ops_capture_state=_OPS_TOOLS.ops_capture_state,
    ops_task_summary=_OPS_TOOLS.ops_task_summary,
    ops_observability_summary=_OPS_TOOLS.ops_observability_summary,
)

_TOOL_ROUTER = ToolRouter(TOOL_REGISTRY, _REPO_CONTEXT, _STATE_STORE)
_RPC_SERVER = JsonRpcServer(_TOOL_ROUTER, _STATE_STORE)


def _resolve_workspace_root(value: str) -> Path:
    return _REPO_CONTEXT.resolve_workspace_root(value)


def journal_append(
    kind: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _STATE_STORE.journal_append(
        kind=kind,
        payload=payload,
        session_id=session_id,
        agent_id=agent_id,
        event_id=event_id,
    )


def snapshot_save(
    state: Dict[str, Any],
    session_id: Optional[str] = None,
    last_applied_seq: Optional[int] = None,
    snapshot_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _STATE_STORE.snapshot_save(
        state=state,
        session_id=session_id,
        last_applied_seq=last_applied_seq,
        snapshot_id=snapshot_id,
    )


def snapshot_load() -> Dict[str, Any]:
    return _STATE_STORE.snapshot_load()


def checkpoint_update(
    last_applied_seq: int,
    snapshot_path: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _STATE_STORE.checkpoint_update(
        last_applied_seq=last_applied_seq,
        snapshot_path=snapshot_path,
        checkpoint_id=checkpoint_id,
    )


def checkpoint_read() -> Dict[str, Any]:
    return _STATE_STORE.checkpoint_read()


def roll_forward_replay(
    checkpoint_path: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    start_seq: Optional[int] = None,
    end_seq: Optional[int] = None,
) -> Dict[str, Any]:
    return _STATE_REBUILDER.roll_forward_replay(
        checkpoint_path=checkpoint_path,
        snapshot_path=snapshot_path,
        start_seq=start_seq,
        end_seq=end_seq,
    )


def continue_state_rebuild(
    checkpoint_path: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    start_seq: Optional[int] = None,
    end_seq: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _STATE_REBUILDER.continue_state_rebuild(
        checkpoint_path=checkpoint_path,
        snapshot_path=snapshot_path,
        start_seq=start_seq,
        end_seq=end_seq,
        session_id=session_id,
    )


def run_verify(timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    return _VERIFY_RUNNER.run_verify(timeout_sec=timeout_sec)


def commit_if_verified(
    message: str, timeout_sec: Optional[int] = None
) -> Dict[str, str]:
    return _COMMIT_MANAGER.commit_if_verified(message, timeout_sec=timeout_sec)


def repo_commit(
    message: Optional[str] = None,
    files: Optional[str] = "auto",
    run_verify: Optional[bool] = None,
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    return _COMMIT_MANAGER.repo_commit(
        message=message,
        files=files,
        run_verify=run_verify,
        timeout_sec=timeout_sec,
    )


def repo_verify(timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    return _REPO_TOOLS.repo_verify(timeout_sec=timeout_sec)


def repo_status_summary() -> Dict[str, Any]:
    return _REPO_TOOLS.repo_status_summary()


def repo_commit_message_suggest(diff: Optional[str] = None) -> Dict[str, Any]:
    return _REPO_TOOLS.repo_commit_message_suggest(diff=diff)


def session_capture_context(
    run_verify: bool = False, log: bool = False
) -> Dict[str, Any]:
    return _REPO_TOOLS.session_capture_context(run_verify=run_verify, log=log)


def tests_suggest(
    diff: Optional[str] = None, failures: Optional[str] = None
) -> Dict[str, Any]:
    return _TEST_SUGGESTER.tests_suggest(diff=diff, failures=failures)


def tests_suggest_from_failures(log_path: str) -> Dict[str, Any]:
    return _TEST_SUGGESTER.tests_suggest_from_failures(log_path)


def ops_compact_context(
    max_chars: Optional[int] = None, include_diff: Optional[bool] = None
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_compact_context(
        max_chars=max_chars, include_diff=include_diff
    )


def ops_handoff_export() -> Dict[str, Any]:
    return _OPS_TOOLS.ops_handoff_export()


def ops_resume_brief(max_chars: Optional[int] = None) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_resume_brief(max_chars=max_chars)


def ops_start_task(
    title: str,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_start_task(
        title=title,
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
        status=status,
    )


def ops_update_task(
    status: Optional[str] = None,
    note: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_update_task(
        status=status,
        note=note,
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
    )


def ops_end_task(
    summary: str,
    next_action: Optional[str] = None,
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_end_task(
        summary=summary,
        next_action=next_action,
        status=status,
        task_id=task_id,
        session_id=session_id,
        agent_id=agent_id,
    )


def ops_capture_state(session_id: Optional[str] = None) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_capture_state(session_id=session_id)


def ops_task_summary(
    session_id: Optional[str] = None, max_chars: Optional[int] = None
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_task_summary(session_id=session_id, max_chars=max_chars)


def ops_observability_summary(
    session_id: Optional[str] = None,
    max_events: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    return _OPS_TOOLS.ops_observability_summary(
        session_id=session_id, max_events=max_events, max_chars=max_chars
    )


def tools_list() -> Dict[str, Any]:
    return _TOOL_ROUTER.tools_list()


def tools_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return _TOOL_ROUTER.tools_call(name, arguments)


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _RPC_SERVER.handle_request(req)


def main() -> None:
    _RPC_SERVER.run()


if __name__ == "__main__":
    main()
