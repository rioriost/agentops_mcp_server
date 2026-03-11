import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentops_mcp_server.commit_manager import CommitManager
from agentops_mcp_server.repo_context import RepoContext
from agentops_mcp_server.state_rebuilder import StateRebuilder
from agentops_mcp_server.state_store import StateStore
from agentops_mcp_server.workflow_response import (
    build_failure_with_defaults,
    canonical_idle_baseline,
    is_canonical_idle_baseline,
    is_valid_active_exact_resume_tx_state,
    is_valid_exact_resume_tx_state,
)


class DummyGitRepo:
    def __init__(self, status_lines=None):
        self.calls = []
        self._status_lines = status_lines or []

    def git(self, *args):
        self.calls.append(args)
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        return ""

    def status_porcelain(self):
        return self._status_lines

    def diff_stat(self):
        return "diff"

    def diff_stat_cached(self):
        return "diff"


class DummyVerifyRunner:
    def __init__(self, result, verify_path="verify"):
        self.result = result
        self.calls = []
        self.verify_path = Path(verify_path)

    def run_verify(self, timeout_sec=None):
        self.calls.append(timeout_sec)
        return self.result


class DummyStateStore:
    def __init__(self):
        self.repo_context = SimpleNamespace(
            tx_state="tx_state.json",
            tx_event_log="tx_event_log.jsonl",
            verify="verify",
            get_repo_root=lambda: "/tmp",
        )

    def read_json_file(self, _path):
        return None


class DummyStateRebuilder:
    def __init__(self, result=None):
        self.result = result

    def rebuild_tx_state(self):
        if self.result is None:
            return {"ok": False}
        return self.result


def _build_manager(status_lines=None, verify_result=None, rebuild_result=None):
    git_repo = DummyGitRepo(status_lines=status_lines)
    verify_runner = DummyVerifyRunner(verify_result or {"ok": True})
    state_store = DummyStateStore()
    state_rebuilder = DummyStateRebuilder(rebuild_result)
    manager = CommitManager(git_repo, verify_runner, state_store, state_rebuilder)
    return manager, git_repo, verify_runner, state_store


def _write_tx_state(
    state_store,
    tx_id=1,
    ticket_id="p4-t3",
    status="in-progress",
    phase=None,
    verify_state_status="not_started",
    commit_state_status="not_started",
    next_action="tx.commit.start",
):
    resolved_phase = phase or status
    verify_state = {"status": verify_state_status, "last_result": None}
    commit_state = {"status": commit_state_status, "last_result": None}
    state = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": resolved_phase,
            "current_step": "commit",
            "last_completed_step": "",
            "next_action": next_action,
            "semantic_summary": "Ready to commit",
            "user_intent": None,
            "session_id": "s1",
            "verify_state": verify_state,
            "commit_state": commit_state,
            "file_intents": [],
        },
        "status": status,
        "next_action": next_action,
        "semantic_summary": "Ready to commit",
        "verify_state": verify_state,
        "commit_state": commit_state,
        "last_applied_seq": 1,
        "integrity": {"state_hash": "hash", "rebuilt_from_seq": 1},
    }
    return state_store.tx_state_save(state)


def test_commit_message_from_status_empty():
    manager, *_ = _build_manager()
    assert manager._commit_message_from_status([]) == "chore: no-op"


def test_normalize_commit_message_truncates_and_cleans():
    manager, *_ = _build_manager()
    assert manager._normalize_commit_message("  hello\nworld  ") == "hello world"
    long = "x" * 200
    normalized = manager._normalize_commit_message(long)
    assert normalized.endswith("...")
    assert len(normalized) <= 80


def test_repo_commit_no_changes():
    manager, *_ = _build_manager()
    result = manager.repo_commit(message="msg", files="auto", run_verify=False)

    assert result["ok"] is False
    assert result["reason"] == "no changes to commit"
    assert result["error_code"] == "invalid_ordering"
    assert result["recoverable"] is True
    assert result["recommended_next_tool"] == "ops_end_task"
    assert (
        result["recommended_action"]
        == "If work is already verified and nothing remains to commit, close the transaction explicitly or make additional changes before retrying commit."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None


def test_shared_resume_helpers_accept_only_canonical_idle_baseline():
    baseline = canonical_idle_baseline()

    assert is_canonical_idle_baseline(baseline) is True
    assert is_valid_exact_resume_tx_state(baseline) is True

    noncanonical = {
        **baseline,
        "next_action": "tx.verify.start",
    }

    assert is_canonical_idle_baseline(noncanonical) is False
    assert is_valid_exact_resume_tx_state(noncanonical) is False


def test_shared_resume_helpers_validate_active_exact_resume_state():
    active_state = {
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "session_id": "s1",
        },
        "status": "verified",
        "next_action": "tx.commit.start",
        "verify_state": {"status": "passed", "last_result": None},
        "commit_state": {"status": "not_started", "last_result": None},
        "semantic_summary": "Ready to commit",
    }

    assert is_valid_active_exact_resume_tx_state(active_state) is True
    assert is_valid_exact_resume_tx_state(active_state) is True

    invalid_active_state = {
        **active_state,
        "next_action": "",
    }

    assert is_valid_active_exact_resume_tx_state(invalid_active_state) is False
    assert is_valid_exact_resume_tx_state(invalid_active_state) is False


def test_repo_commit_no_changes_emits_commit_fail_event(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(
        state_store,
        status="verified",
        phase="verified",
        verify_state_status="passed",
    )

    manager = CommitManager(
        DummyGitRepo(status_lines=[]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )

    result = manager.repo_commit(message="msg", files="auto", run_verify=False)

    assert result["ok"] is False
    assert result["reason"] == "no changes to commit"

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.commit.start",
        "tx.commit.fail",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["commit_state"]["status"] == "failed"
    assert active_tx["commit_state"]["last_result"]["error"] == "no changes to commit"
    assert active_tx["status"] == "verified"
    assert active_tx["phase"] == "verified"


def test_repo_commit_auto_message(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(message=None, files="auto", run_verify=False)

    assert result["ok"] is True
    assert result["message"] == "chore: update 1 file(s)"
    assert ("add", "-A") in git_repo.calls


def test_repo_commit_no_files_specified_returns_structured_failure():
    manager, *_ = _build_manager(status_lines=[" M file.txt"])

    result = manager.repo_commit(message="msg", files=[], run_verify=False)

    assert result["ok"] is False
    assert result["reason"] == "no files specified"
    assert result["error_code"] == "invalid_ordering"
    assert result["recoverable"] is True
    assert result["recommended_next_tool"] == "repo_commit"
    assert (
        result["recommended_action"]
        == "Specify commit paths or use auto staging before retrying commit."
    )


def test_commit_if_verified_runs_verify(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["ok"] is True
    assert result["sha"] == "abc123"
    assert result["message"] == "message"
    assert result["tx_status"] == "committed"
    assert result["tx_phase"] == "committed"
    assert result["canonical_status"] == "committed"
    assert result["canonical_phase"] == "committed"
    assert result["next_action"] == "tx.end.done"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] == "ops_end_task"
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "p4-t3"
    assert result["current_step"] is None
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "passed"
    assert result["integrity_status"] in {"ok", None}
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx"] == {}
    assert manager.verify_runner.calls == [5]
    assert ("add", "-A") in manager.git_repo.calls


def test_commit_if_verified_verify_failure_raises_structured_failure(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner(
            {"ok": False, "returncode": 7, "stdout": "", "stderr": "boom"}
        ),
        state_store,
        state_rebuilder,
    )

    with pytest.raises(RuntimeError) as excinfo:
        manager.commit_if_verified("message", timeout_sec=5)

    failure = excinfo.value.args[0]
    assert failure["ok"] is False
    assert failure["error_code"] == "verify_failed"
    assert failure["recoverable"] is True
    assert failure["recommended_next_tool"] == "repo_verify"
    assert (
        failure["recommended_action"]
        == "Repair the verification failure and rerun verification before attempting commit."
    )
    assert failure["reason"] == "verify failed (code=7): boom"


def test_commit_if_verified_emits_tx_commit_events(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)
    assert result["ok"] is True
    assert result["sha"] == "abc123"
    assert result["tx_status"] == "committed"
    assert result["tx_phase"] == "committed"
    assert result["next_action"] == "tx.end.done"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] == "ops_end_task"

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    event_by_type = {event["event_type"]: event for event in events}

    assert event_types == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
        "tx.commit.start",
        "tx.commit.done",
    ]

    verify_start = event_by_type["tx.verify.start"]

    assert verify_start["phase"] == "checking"
    assert "command" in verify_start["payload"]

    verify_pass = event_by_type["tx.verify.pass"]
    assert verify_pass["phase"] == "verified"
    assert verify_pass["payload"]["ok"] is True

    commit_start = event_by_type["tx.commit.start"]
    assert commit_start["phase"] == "verified"
    assert commit_start["payload"]["message"] == "message"

    commit_done = event_by_type["tx.commit.done"]
    assert commit_done["phase"] == "committed"
    assert commit_done["payload"]["sha"] == "abc123"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"
    assert active_tx["next_action"] in {"tx.end.done", "tx.begin"}
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t3"


def test_commit_if_verified_preserves_opaque_canonical_tx_id_and_nonterminal_commit_state(
    tmp_path, monkeypatch
):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=42,
        ticket_id="v0.6.0/p2-t01",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "v0.6.0/p2-t01", "ticket_title": "p2-t01"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(
        state_store,
        tx_id=42,
        ticket_id="v0.6.0/p2-t01",
        verify_state_status="running",
    )

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["ok"] is True
    assert result["tx_status"] == "committed"
    assert result["tx_phase"] == "committed"
    assert result["canonical_status"] == "committed"
    assert result["canonical_phase"] == "committed"
    assert result["next_action"] == "tx.end.done"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] == "ops_end_task"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx_id"] == 42
    assert result["active_ticket_id"] == "v0.6.0/p2-t01"
    assert result["active_tx"] == {}


def test_repo_commit_verify_failure_raises_structured_failure(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner(
            {"ok": False, "returncode": 9, "stdout": "", "stderr": "verify failed"}
        ),
        state_store,
        state_rebuilder,
    )

    with pytest.raises(RuntimeError) as excinfo:
        manager.repo_commit(message="msg", files="auto", run_verify=True, timeout_sec=5)

    failure = excinfo.value.args[0]
    assert failure["ok"] is False
    assert failure["error_code"] == "verify_failed"
    assert failure["recoverable"] is True
    assert failure["recommended_next_tool"] == "repo_verify"
    assert (
        failure["recommended_action"]
        == "Repair the verification failure and rerun verification before attempting commit."
    )
    assert failure["reason"] == "verify failed (code=9): verify failed"


def test_build_failure_with_defaults_defaults_commit_required():
    result = build_failure_with_defaults(
        error_code="commit_required",
        reason="complete commit workflow first",
    )

    assert result["ok"] is False
    assert result["error_code"] == "commit_required"
    assert result["recoverable"] is True
    assert result["recommended_next_tool"] == "repo_commit"
    assert (
        result["recommended_action"]
        == "Complete the commit workflow before attempting terminal completion."
    )


def test_build_failure_with_defaults_defaults_terminal_transaction():
    result = build_failure_with_defaults(
        error_code="terminal_transaction",
        reason="cannot mutate a terminal transaction",
    )

    assert result["ok"] is False
    assert result["error_code"] == "terminal_transaction"
    assert result["recoverable"] is False
    assert result["recommended_next_tool"] == "ops_start_task"
    assert (
        result["recommended_action"]
        == "Do not emit more lifecycle events for a terminal transaction; start a new ticket only when canonical state allows it."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None


def test_build_failure_with_defaults_defaults_begin_required():
    result = build_failure_with_defaults(
        error_code="begin_required",
        reason="tx.begin required before lifecycle updates",
    )

    assert result["ok"] is False
    assert result["error_code"] == "begin_required"
    assert result["recoverable"] is True
    assert result["recommended_next_tool"] == "ops_start_task"
    assert (
        result["recommended_action"]
        == "Start or resume the canonical transaction before emitting lifecycle events."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None


def test_build_failure_with_defaults_defaults_resume_required():
    result = build_failure_with_defaults(
        error_code="resume_required",
        reason="resume the active transaction first",
    )

    assert result["ok"] is False
    assert result["error_code"] == "resume_required"
    assert result["recoverable"] is True
    assert result["recommended_next_tool"] == "ops_update_task"
    assert (
        result["recommended_action"]
        == "Resume or complete the active transaction before starting a different ticket."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None


def test_build_failure_with_defaults_defaults_historical_repair_required():
    result = build_failure_with_defaults(
        error_code="historical_repair_required",
        reason="repair damaged canonical history before resuming",
    )

    assert result["ok"] is False
    assert result["error_code"] == "historical_repair_required"
    assert result["recoverable"] is False
    assert result["recommended_next_tool"] == "tx_state_rebuild"
    assert (
        result["recommended_action"]
        == "Historical repair is required before resume-safe automation can continue. Preserve the invalid event metadata, repair or replace the damaged canonical history, and avoid reusing human ticket labels as canonical tx_id values."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None


def test_build_failure_with_defaults_defaults_tx_id_collision():
    result = build_failure_with_defaults(
        error_code="tx_id_collision",
        reason="canonical tx_id collision detected",
    )

    assert result["ok"] is False
    assert result["error_code"] == "tx_id_collision"
    assert result["recoverable"] is False
    assert result["recommended_next_tool"] == "tx_state_rebuild"
    assert (
        result["recommended_action"]
        == "Do not treat the collided history as healthy. Repair the historical log, assign future canonical tx_id values as opaque identifiers, and keep user-facing ticket labels separate from canonical transaction identity."
    )
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None


def test_commit_if_verified_keeps_commit_nonterminal_until_explicit_end(
    tmp_path, monkeypatch
):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=7,
        ticket_id="p2-t01",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p2-t01", "ticket_title": "p2-t01"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(
        state_store,
        tx_id=7,
        ticket_id="p2-t01",
        verify_state_status="running",
    )

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["ok"] is True
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] == "ops_end_task"
    assert result["next_action"] == "tx.end.done"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == 7
    assert active_tx["ticket_id"] == "p2-t01"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["next_action"] == "tx.end.done"


def test_commit_if_verified_backfills_tx_begin_when_log_empty(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)
    assert result["sha"] == "abc123"

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
        "tx.commit.start",
        "tx.commit.done",
    ]


def test_repo_commit_verify_failure_raises():
    manager, *_ = _build_manager(
        status_lines=[" M file.txt"],
        verify_result={"ok": False, "returncode": 1, "stderr": "nope", "stdout": ""},
    )

    with pytest.raises(RuntimeError) as excinfo:
        manager.repo_commit(run_verify=True)

    failure = excinfo.value.args[0]
    assert failure["ok"] is False
    assert failure["error_code"] == "invalid_ordering"
    assert failure["reason"] == "verify.start not recorded; active_tx missing"
    assert failure["recommended_next_tool"] == "repo_verify"


def test_commit_if_verified_logs_verify_failure_diagnostics(tmp_path, monkeypatch):
    tx_repo_context = RepoContext(tmp_path)
    tx_state_store = StateStore(tx_repo_context)
    tx_state_rebuilder = StateRebuilder(tx_repo_context, tx_state_store)
    tx_state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = tx_state_rebuilder.rebuild_tx_state()
    tx_state_store.tx_state_save(rebuild["state"])
    _write_tx_state(tx_state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner(
            {"ok": False, "returncode": 1, "stderr": "nope", "stdout": ""}
        ),
        tx_state_store,
        tx_state_rebuilder,
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="verify failed"):
        manager.commit_if_verified("message", timeout_sec=5)

    assert tx_repo_context.errors.exists() is False


def test_commit_if_verified_synchronizes_verify_start_state(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store)

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["sha"] == "abc123"
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["verify_state"]["last_result"]["ok"] is True
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["commit_state"]["last_result"]["sha"] == "abc123"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"
    assert active_tx["semantic_summary"] == "Commit completed"
    assert active_tx["next_action"] == "tx.end.done"
    assert active_tx["semantic_summary"] == "Commit completed"
    assert active_tx["next_action"] == "tx.end.done"
    assert tx_state["last_applied_seq"] == 5


def test_repo_commit_run_verify_synchronizes_verify_state_before_commit(
    tmp_path, monkeypatch
):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store)

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.repo_commit(message="message", run_verify=True)

    assert result["ok"] is True
    assert result["sha"] == "abc123"
    assert result["tx_status"] == "committed"
    assert result["tx_phase"] == "committed"
    assert result["next_action"] == "tx.end.done"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] == "ops_end_task"

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
        "tx.commit.start",
        "tx.commit.done",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"


def test_ensure_verify_started_does_not_accept_drifted_rebuild_as_running():
    class RebuildAwareStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.read_count = 0

        def read_json_file(self, _path):
            self.read_count += 1
            if self.read_count == 1:
                return {
                    "active_tx": {
                        "verify_state": {"status": "not_started"},
                    }
                }
            return None

    drifted_state = {
        "active_tx": {
            "verify_state": {"status": "running"},
        },
        "integrity": {
            "drift_detected": True,
        },
    }
    state_store = RebuildAwareStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": drifted_state}),
    )
    manager._verify_started_in_call = True

    with pytest.raises(RuntimeError) as excinfo:
        manager._ensure_verify_started()

    failure = excinfo.value.args[0]
    assert failure["ok"] is False
    assert failure["error_code"] == "invalid_ordering"
    assert failure["reason"] == "verify.start not recorded; active_tx missing"
    assert failure["recommended_next_tool"] == "repo_verify"


def test_emit_tx_event_does_not_use_drifted_rebuild_for_append_and_save():
    class AppendOnlyStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_calls = []
            self.append_and_save_calls = []
            self.saved_states = []

        def read_json_file(self, _path):
            return None

        def tx_event_append(self, **kwargs):
            self.append_calls.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True}

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

    drifted_state = {
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "status": "checking",
            "phase": "checking",
            "current_step": "commit",
            "session_id": "s1",
        },
        "integrity": {
            "drift_detected": True,
        },
    }
    state_store = AppendOnlyStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": drifted_state}),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 1,
        "ticket_id": "p4-t3",
        "next_action": "tx.verify.start",
        "session_id": "s1",
    }

    result = manager._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": "verify"},
    )

    assert result["ok"] is True
    assert state_store.append_calls == []
    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_and_save_calls[0]["event_type"] == "tx.verify.start"
    assert state_store.saved_states == []


def test_repo_commit_with_files_list_adds_specific_paths(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files="a.py, b.py")

    assert result["ok"] is True
    assert ("add", "a.py", "b.py") in git_repo.calls


def test_repo_commit_with_files_empty_returns_reason():
    manager, *_ = _build_manager(status_lines=[" M file.txt"])

    result = manager.repo_commit(files=" , ")

    assert result["ok"] is False
    assert result["reason"] == "no files specified"


def test_load_tx_context_missing_state_returns_none():
    manager, *_ = _build_manager()
    assert manager._load_tx_context() is None


def test_load_tx_context_rejects_invalid_shapes():
    class InvalidStateStore(DummyStateStore):
        def __init__(self, state):
            super().__init__()
            self.state = state

        def read_json_file(self, _path):
            return self.state

    invalid_states = [
        {"active_tx": []},
        {"active_tx": {"tx_id": "", "ticket_id": "p4-t3", "session_id": "s1"}},
        {"active_tx": {"tx_id": 1, "ticket_id": "", "session_id": "s1"}},
        {"active_tx": {"tx_id": 1, "ticket_id": "p4-t3", "session_id": ""}},
    ]

    for state in invalid_states:
        manager = CommitManager(
            DummyGitRepo(),
            DummyVerifyRunner({"ok": True}),
            InvalidStateStore(state),
            DummyStateRebuilder(),
        )
        assert manager._load_tx_context() is None


def test_load_tx_context_defaults_next_action_when_missing():
    class FallbackStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p4-t3",
                    "status": "",
                    "phase": "",
                    "current_step": "",
                    "session_id": " s1 ",
                }
            }

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        FallbackStateStore(),
        DummyStateRebuilder(),
    )

    assert manager._load_tx_context() is None


def test_load_tx_context_uses_top_level_next_action():
    class StatusFallbackStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p4-t3",
                    "status": "verified",
                    "phase": "",
                    "current_step": "review",
                    "session_id": "s1",
                },
                "next_action": "tx.commit.start",
            }

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        StatusFallbackStateStore(),
        DummyStateRebuilder(),
    )

    assert manager._load_tx_context() is None


def test_commit_message_from_status_counts_files():
    manager, *_ = _build_manager()
    assert (
        manager._commit_message_from_status([" M a.txt", "A b.txt"])
        == "chore: update 2 file(s)"
    )


def test_branch_name_falls_back_to_unknown():
    class FailingGitRepo(DummyGitRepo):
        def git(self, *args):
            raise RuntimeError("boom")

    manager = CommitManager(
        FailingGitRepo(),
        DummyVerifyRunner({"ok": True}),
        DummyStateStore(),
        DummyStateRebuilder(),
    )
    assert manager._branch_name() == "unknown"


def test_repo_commit_with_files_none_adds_all(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files=None)

    assert result["ok"] is True
    assert ("add", "-A") in git_repo.calls


def test_commit_if_verified_verify_failure_emits_event(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="running")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": False, "returncode": 2, "stderr": "nope"}),
        state_store,
        state_rebuilder,
    )

    with pytest.raises(RuntimeError, match="verify failed"):
        manager.commit_if_verified("message", timeout_sec=1)

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]

    assert event_types == ["tx.begin", "tx.verify.start", "tx.verify.fail"]


def test_commit_if_verified_rejects_verify_result_without_verify_start():
    class RebuildAwareStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.read_count = 0
            self.events = []

        def read_json_file(self, _path):
            self.read_count += 1
            if self.read_count == 1:
                return {
                    "active_tx": {
                        "verify_state": {"status": "not_started"},
                    }
                }
            return None

        def read_last_json_line(self, _path):
            return None

        def tx_event_append(self, **kwargs):
            self.events.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

        def tx_event_append_and_state_save(self, **kwargs):
            self.events.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

    state_store = RebuildAwareStateStore()
    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        DummyStateRebuilder({"ok": False}),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 1,
        "ticket_id": "p4-t3",
        "next_action": "tx.verify.start",
        "session_id": "s1",
    }

    with pytest.raises(RuntimeError) as excinfo:
        manager.commit_if_verified("message", timeout_sec=1)

    failure = excinfo.value.args[0]
    assert failure["ok"] is False
    assert failure["error_code"] == "invalid_ordering"
    assert failure["reason"] == "verify.start not recorded; active_tx missing"
    assert failure["recommended_next_tool"] == "repo_verify"

    event_types = [event["event_type"] for event in state_store.events]
    assert event_types == ["tx.begin", "tx.verify.start"]


def test_repo_commit_with_verify_updates_verify_state(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="not_started")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    original_run = subprocess.run
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (
            None
            if args and args[0][:2] == ["git", "commit"]
            else original_run(*args, **kwargs)
        ),
    )

    result = manager.repo_commit(message="message", run_verify=True)

    assert result["ok"] is True

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
        "tx.commit.start",
        "tx.commit.done",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["verify_state"]["last_result"]["returncode"] == 0
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"


def test_repo_commit_with_verify_then_commit_failure_keeps_verified_state(
    tmp_path, monkeypatch
):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="not_started")

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )

    def failing_run_git_commit(_message):
        manager._emit_tx_event(
            event_type="tx.commit.fail",
            payload={"error": "git commit failed", "summary": "commit failed"},
            phase_override="verified",
        )
        raise RuntimeError("git commit failed")

    monkeypatch.setattr(manager, "_run_git_commit", failing_run_git_commit)

    with pytest.raises(RuntimeError, match="git commit failed"):
        manager.repo_commit(message="message", run_verify=True)

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
        "tx.commit.start",
        "tx.commit.fail",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["verify_state"]["last_result"]["returncode"] == 0
    assert active_tx["commit_state"]["status"] == "failed"
    assert active_tx["commit_state"]["last_result"]["error"] == "git commit failed"
    assert active_tx["status"] == "verified"
    assert active_tx["phase"] == "verified"


def test_repo_verify_success_records_canonical_verify_events(tmp_path):
    from agentops_mcp_server.repo_tools import RepoTools

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="not_started")

    verify_runner = DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"})
    tools = RepoTools(
        DummyGitRepo(status_lines=[" M file.txt"]),
        verify_runner,
        state_store,
        state_rebuilder,
    )

    result = tools.repo_verify(timeout_sec=7)

    assert result["ok"] is True
    assert verify_runner.calls == [7]

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.pass",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["status"] == "verified"
    assert active_tx["phase"] == "verified"


def test_repo_verify_failure_records_canonical_verify_fail_event(tmp_path):
    from agentops_mcp_server.repo_tools import RepoTools

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(state_store, verify_state_status="not_started")

    verify_runner = DummyVerifyRunner(
        {"ok": False, "returncode": 2, "stdout": "", "stderr": "nope"}
    )
    tools = RepoTools(
        DummyGitRepo(status_lines=[" M file.txt"]),
        verify_runner,
        state_store,
        state_rebuilder,
    )

    result = tools.repo_verify(timeout_sec=3)

    assert result["ok"] is False
    assert verify_runner.calls == [3]

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.verify.start",
        "tx.verify.fail",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "failed"
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"


def test_repo_verify_terminal_transaction_falls_back_without_tx_context(tmp_path):
    from agentops_mcp_server.repo_tools import RepoTools

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(
        state_store,
        status="done",
        phase="done",
        verify_state_status="passed",
        commit_state_status="passed",
    )

    verify_runner = DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"})
    tools = RepoTools(
        DummyGitRepo(status_lines=[" M file.txt"]),
        verify_runner,
        state_store,
        state_rebuilder,
    )

    result = tools.repo_verify(timeout_sec=1)

    assert result["ok"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "ok"
    assert verify_runner.calls == [1]

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_type"] for event in events] == ["tx.begin"]


def test_diff_summary_handles_exception():
    class FailingDiffGitRepo(DummyGitRepo):
        def diff_stat(self):
            raise RuntimeError("boom")

        def diff_stat_cached(self):
            raise RuntimeError("boom")

    manager = CommitManager(
        FailingDiffGitRepo(),
        DummyVerifyRunner({"ok": True}),
        DummyStateStore(),
        DummyStateRebuilder(),
    )

    assert manager._diff_summary() == "no changes"
    assert manager._diff_summary(cached=True) == "no changes"


def test_event_log_empty_true_when_missing(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        state_rebuilder,
    )

    assert manager._event_log_empty() is True


def test_ensure_tx_begin_returns_when_context_missing():
    manager, *_ = _build_manager()
    manager._ensure_tx_begin()


def test_ensure_tx_begin_skips_when_event_log_not_empty():
    class EventLogStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.appended = []

        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p4-t3",
                    "phase": "in-progress",
                    "current_step": "commit",
                    "session_id": "s1",
                }
            }

        def read_last_json_line(self, _path):
            return {"event_type": "tx.begin"}

        def tx_event_append_and_state_save(self, **kwargs):
            self.appended.append(kwargs)
            return {"ok": True}

    state_store = EventLogStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder(),
    )

    manager._ensure_tx_begin()

    assert state_store.appended == []


def test_ensure_tx_begin_uses_rebuild_active_transaction_when_materialized_missing():
    class MissingStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.saved_states = []
            self.appended = []

        def read_json_file(self, _path):
            return None

        def read_last_json_line(self, _path):
            return None

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

        def tx_event_append(self, **kwargs):
            self.appended.append(kwargs)
            return {"ok": True}

    rebuild_state = {
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "status": "checking",
            "phase": "checking",
            "current_step": "resume-step",
            "next_action": "tx.verify.start",
            "session_id": "s1",
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
        "status": "checking",
        "next_action": "tx.verify.start",
        "verify_state": {"status": "not_started", "last_result": None},
        "commit_state": {"status": "not_started", "last_result": None},
        "semantic_summary": "Resume verification",
        "integrity": {
            "drift_detected": False,
            "active_tx_source": "active_candidate",
        },
    }
    state_store = MissingStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuild_state}),
    )

    manager._ensure_tx_begin()

    assert state_store.appended == []
    assert state_store.saved_states == []


def test_ensure_tx_begin_raises_structured_failure_when_rebuild_drift_detected():
    class DriftStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p4-t3",
                    "phase": "in-progress",
                    "current_step": "commit",
                    "session_id": "s1",
                }
            }

        def read_last_json_line(self, _path):
            return None

    rebuild_state = {
        "active_tx": {
            "tx_id": 0,
            "ticket_id": "none",
            "status": "planned",
            "phase": "planned",
            "current_step": "none",
            "next_action": "",
            "session_id": "",
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
        "integrity": {
            "drift_detected": True,
            "active_tx_source": "none",
        },
        "rebuild_warning": "duplicate tx.begin",
        "rebuild_invalid_seq": 1,
        "rebuild_observed_mismatch": {
            "drift_reason": "duplicate tx.begin",
            "last_applied_seq": 1,
            "invalid_reason": "duplicate tx.begin",
            "invalid_event": {
                "seq": 2,
                "event_type": "tx.begin",
                "tx_id": 1,
                "ticket_id": "p4-t3",
            },
        },
    }
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        DriftStateStore(),
        DummyStateRebuilder({"ok": True, "state": rebuild_state}),
    )

    manager._ensure_tx_begin()


def test_ensure_verify_started_returns_when_already_running():
    class RunningStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {
                "verify_state": {"status": "running"},
                "active_tx": {
                    "verify_state": {"status": "running"},
                },
            }

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        RunningStateStore(),
        DummyStateRebuilder(),
    )

    with pytest.raises(
        RuntimeError, match="verify.start not recorded; active_tx missing"
    ):
        manager._ensure_verify_started()


def test_ensure_verify_started_requires_begin_when_not_started():
    class NotStartedStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {
                "verify_state": {"status": "not_started"},
                "active_tx": {
                    "verify_state": {"status": "not_started"},
                },
            }

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        NotStartedStateStore(),
        DummyStateRebuilder(),
    )

    with pytest.raises(
        RuntimeError,
        match="verify.start not recorded; active_tx missing",
    ):
        manager._ensure_verify_started()


def test_ensure_verify_started_recovers_running_state_from_rebuild():
    class RebuildRecoveryStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.saved_states = []

        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "verify_state": {"status": "not_started"},
                }
            }

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

    rebuilt_state = {
        "verify_state": {"status": "running"},
        "active_tx": {
            "verify_state": {"status": "running"},
        },
        "integrity": {
            "drift_detected": False,
        },
    }
    state_store = RebuildRecoveryStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuilt_state}),
    )
    manager._verify_started_in_call = True

    with pytest.raises(
        RuntimeError, match="verify.start not recorded; active_tx missing"
    ):
        manager._ensure_verify_started()

    assert state_store.saved_states == []


def test_emit_tx_event_uses_rebuilt_state_when_tx_state_missing():
    class RebuiltStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_and_save_calls = []
            self.append_calls = []

        def read_json_file(self, _path):
            return None

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

        def tx_event_append(self, **kwargs):
            self.append_calls.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

    rebuilt_state = {
        "active_tx": {
            "tx_id": "stale",
            "ticket_id": "stale-ticket",
            "status": "old",
            "phase": "old",
            "current_step": "old-step",
            "session_id": "stale-session",
        },
        "integrity": {
            "drift_detected": False,
        },
    }
    state_store = RebuiltStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuilt_state}),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 1,
        "ticket_id": "p4-t3",
        "next_action": "tx.verify.start",
        "session_id": "s1",
    }

    result = manager._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": "verify"},
    )

    assert result["ok"] is True
    assert state_store.append_calls == []
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"] is None
    assert saved_state["verify_state"] is None
    assert saved_state["commit_state"] is None
    assert saved_state["next_action"] == "tx.begin"
    assert saved_state["integrity"] == {}


def test_emit_tx_event_saves_rebuilt_state_after_append_fallback():
    class AppendFallbackStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_calls = []
            self.saved_states = []

        def read_json_file(self, _path):
            return None

        def tx_event_append(self, **kwargs):
            self.append_calls.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

    class TwoPhaseRebuilder:
        def __init__(self):
            self.calls = 0

        def rebuild_tx_state(self):
            self.calls += 1
            if self.calls == 1:
                return {"ok": False}
            return {
                "ok": True,
                "state": {
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "p4-t3",
                        "phase": "checking",
                        "current_step": "commit",
                        "session_id": "s1",
                    },
                    "integrity": {
                        "drift_detected": False,
                    },
                },
            }

    state_store = AppendFallbackStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        TwoPhaseRebuilder(),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 1,
        "ticket_id": "p4-t3",
        "next_action": "tx.verify.start",
        "session_id": "s1",
    }

    with pytest.raises(AttributeError, match="tx_event_append_and_state_save"):
        manager._emit_tx_event(
            event_type="tx.verify.start",
            payload={"command": "verify"},
        )

    assert state_store.append_calls == []
    assert state_store.saved_states == []


def test_repo_commit_with_single_file_string_adds_specific_path(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files="a.py")

    assert result["ok"] is True
    assert ("add", "a.py") in git_repo.calls


def test_repo_commit_with_files_empty_string_normalizes_to_auto(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files="   ")

    assert result["ok"] is True
    assert ("add", "-A") in git_repo.calls


def test_repo_commit_returns_summary_from_run_git_commit(monkeypatch):
    manager, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(
        manager, "_run_git_commit", lambda msg: ("sha-123", "cached diff summary")
    )

    result = manager.repo_commit(message="msg", files="auto", run_verify=False)

    assert result["ok"] is True
    assert result["sha"] == "sha-123"
    assert result["message"] == "msg"
    assert result["summary"] == "cached diff summary"
    assert result["tx_status"] == ""
    assert result["tx_phase"] == ""
    assert result["canonical_status"] == ""
    assert result["canonical_phase"] == ""
    assert result["next_action"] == "tx.begin"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] is None
    assert result["active_ticket_id"] is None
    assert result["current_step"] is None
    assert result["verify_status"] is None
    assert result["commit_status"] is None
    assert result["integrity_status"] is None
    assert result["can_start_new_ticket"] is True
    assert result["resume_required"] is False
    assert result["active_tx"] == {}


def test_run_git_commit_failure_emits_event(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    state_store.tx_event_append(
        tx_id=1,
        ticket_id="p4-t3",
        event_type="tx.begin",
        phase="in-progress",
        step_id="commit",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ticket_id": "p4-t3", "ticket_title": "p4-t3"},
    )
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])
    _write_tx_state(
        state_store,
        verify_state_status="running",
        commit_state_status="running",
    )

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True}),
        state_store,
        state_rebuilder,
    )

    def fail_run(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(RuntimeError, match="commit failed"):
        manager._run_git_commit("message")

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]

    assert "tx.commit.fail" in event_types


def test_emit_tx_begin_with_context_appends_without_materialized_state():
    class AppendOnlyStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_and_save_calls = []

        def read_json_file(self, _path):
            return None

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True}

    state_store = AppendOnlyStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": False}),
    )

    manager._emit_tx_begin_with_context(
        {
            "tx_id": 7,
            "ticket_id": "p4-t7",
            "phase": "checking",
            "step_id": "commit",
            "session_id": "s7",
        }
    )

    assert len(state_store.append_and_save_calls) == 1
    saved = state_store.append_and_save_calls[0]
    assert saved["event_type"] == "tx.begin"
    assert saved["ticket_id"] == "p4-t7"
    assert saved["state"]["active_tx"]["tx_id"] == 7
    assert saved["state"]["active_tx"]["ticket_id"] == "p4-t7"
    assert saved["state"]["active_tx"]["status"] == "in-progress"
    assert saved["state"]["active_tx"]["phase"] == "in-progress"
    assert saved["state"]["active_tx"]["current_step"] == "none"
    assert saved["state"]["active_tx"]["session_id"] == "s7"
    assert saved["state"]["active_tx"]["verify_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved["state"]["active_tx"]["commit_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved["state"]["status"] == "in-progress"
    assert saved["state"]["next_action"] == "tx.verify.start"
    assert saved["state"]["semantic_summary"] == "Transaction started"


def test_ensure_verify_started_requires_materialized_tx_state():
    class MissingStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return None

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        MissingStateStore(),
        DummyStateRebuilder(),
    )

    with pytest.raises(
        RuntimeError,
        match="verify.start not recorded; active_tx missing",
    ):
        manager._ensure_verify_started()


def test_ensure_verify_started_requires_active_tx():
    class MissingActiveTxStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {}

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        MissingActiveTxStateStore(),
        DummyStateRebuilder(),
    )

    with pytest.raises(
        RuntimeError,
        match="verify.start not recorded; active_tx missing",
    ):
        manager._ensure_verify_started()


def test_emit_tx_event_returns_none_without_context():
    manager, *_ = _build_manager()
    manager._load_tx_context = lambda: None

    result = manager._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": "verify"},
    )

    assert result is None


def test_emit_tx_event_uses_materialized_state_when_available():
    class MaterializedStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_and_save_calls = []

        def read_json_file(self, _path):
            return {
                "active_tx": {
                    "tx_id": 99,
                    "ticket_id": "stale-ticket",
                    "status": "old",
                    "phase": "old",
                    "current_step": "old-step",
                    "session_id": "stale-session",
                }
            }

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True, "event_type": kwargs["event_type"]}

    state_store = MaterializedStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": False}),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 5,
        "ticket_id": "p4-t5",
        "next_action": "tx.commit.start",
        "session_id": "s5",
    }

    result = manager._emit_tx_event(
        event_type="tx.commit.start",
        payload={"message": "msg"},
    )

    assert result["ok"] is True
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state == {
        "active_tx": None,
        "verify_state": None,
        "commit_state": None,
        "status": None,
        "semantic_summary": None,
        "next_action": "tx.begin",
        "integrity": {},
    }


def test_workflow_guidance_returns_empty_defaults_when_tx_state_missing():
    manager, *_ = _build_manager()

    result = manager._workflow_guidance()

    assert result == {
        "tx_status": "",
        "tx_phase": "",
        "next_action": "tx.begin",
        "terminal": False,
        "requires_followup": True,
        "followup_tool": None,
        "canonical_status": "",
        "canonical_phase": "",
        "active_tx_id": None,
        "active_ticket_id": None,
        "current_step": None,
        "verify_status": None,
        "commit_status": None,
        "integrity_status": None,
        "can_start_new_ticket": True,
        "resume_required": False,
        "active_tx": {},
    }


def test_workflow_guidance_returns_empty_defaults_when_active_tx_missing():
    class MissingActiveTxStateStore(DummyStateStore):
        def read_json_file(self, _path):
            return {}

    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        MissingActiveTxStateStore(),
        DummyStateRebuilder(),
    )

    result = manager._workflow_guidance()

    assert result == {
        "tx_status": "",
        "tx_phase": "",
        "next_action": "",
        "terminal": False,
        "requires_followup": False,
        "followup_tool": None,
        "canonical_status": "",
        "canonical_phase": "",
        "active_tx_id": None,
        "active_ticket_id": None,
        "current_step": None,
        "verify_status": None,
        "commit_status": None,
        "integrity_status": None,
        "can_start_new_ticket": True,
        "resume_required": False,
        "active_tx": {},
    }


def test_repo_commit_with_comma_separated_files_adds_each_path(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files="a.py, b.py , c.py")

    assert result["ok"] is True
    assert ("add", "a.py", "b.py", "c.py") in git_repo.calls


def test_repo_commit_with_non_list_non_string_files_coerces_to_single_path(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(files=123)

    assert result["ok"] is True
    assert ("add", "123") in git_repo.calls


def test_active_tx_from_state_rejects_invalid_shapes():
    manager, *_ = _build_manager()

    assert manager._active_tx_from_state(None) is None
    assert manager._active_tx_from_state({"active_tx": []}) is None
    assert (
        manager._active_tx_from_state(
            {"active_tx": {"tx_id": True, "ticket_id": "p4-t3", "session_id": "s1"}}
        )
        is None
    )
    assert (
        manager._active_tx_from_state(
            {"active_tx": {"tx_id": 1, "ticket_id": " none ", "session_id": "s1"}}
        )
        is None
    )
    assert (
        manager._active_tx_from_state(
            {"active_tx": {"tx_id": 1, "ticket_id": "p4-t3", "session_id": ""}}
        )
        is None
    )


def test_active_tx_from_state_applies_phase_and_step_fallbacks():
    manager, *_ = _build_manager()

    assert (
        manager._active_tx_from_state(
            {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": " p4-t3 ",
                    "status": " verified ",
                    "phase": " ",
                    "current_step": " ",
                    "session_id": " s1 ",
                }
            }
        )
        is None
    )

    assert (
        manager._active_tx_from_state(
            {
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p4-t3",
                    "status": " ",
                    "phase": " ",
                    "current_step": " review ",
                    "session_id": "s1",
                }
            }
        )
        is None
    )


def test_matching_active_context_from_rebuild_handles_failure_and_drift():
    manager, *_ = _build_manager()
    manager.state_rebuilder = DummyStateRebuilder({"ok": False})

    matched, state, integrity = manager._matching_active_context_from_rebuild(
        {"tx_id": 1, "ticket_id": "p4-t3"}
    )
    assert (matched, state, integrity) == (None, None, None)

    drifted_state = {
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "phase": "checking",
            "current_step": "resume-step",
            "session_id": "s1",
        },
        "integrity": {"drift_detected": True},
    }
    manager.state_rebuilder = DummyStateRebuilder({"ok": True, "state": drifted_state})

    matched, state, integrity = manager._matching_active_context_from_rebuild(
        {"tx_id": 1, "ticket_id": "p4-t3"}
    )
    assert matched is None
    assert state == drifted_state
    assert integrity == {"drift_detected": True}


def test_matching_active_context_from_rebuild_rejects_nonmatching_and_terminal_states():
    manager, *_ = _build_manager()

    nonmatching_state = {
        "active_tx": {
            "tx_id": 2,
            "ticket_id": "other-ticket",
            "phase": "checking",
            "current_step": "resume-step",
            "session_id": "s1",
        },
        "integrity": {"drift_detected": False},
    }
    manager.state_rebuilder = DummyStateRebuilder(
        {"ok": True, "state": nonmatching_state}
    )

    matched, state, integrity = manager._matching_active_context_from_rebuild(
        {"tx_id": 1, "ticket_id": "p4-t3"}
    )
    assert matched is None
    assert state == nonmatching_state
    assert integrity == {"drift_detected": False}

    terminal_state = {
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "phase": "done",
            "current_step": "resume-step",
            "session_id": "s1",
        },
        "integrity": {"drift_detected": False},
    }
    manager.state_rebuilder = DummyStateRebuilder({"ok": True, "state": terminal_state})

    matched, state, integrity = manager._matching_active_context_from_rebuild(
        {"tx_id": 1, "ticket_id": "p4-t3"}
    )
    assert matched is None
    assert state == terminal_state
    assert integrity == {"drift_detected": False}


def test_matching_active_context_from_rebuild_accepts_ticket_id_match_with_different_tx_id():
    manager, *_ = _build_manager()

    rebuilt_state = {
        "active_tx": {
            "tx_id": 9,
            "ticket_id": "p4-t3",
            "status": "checking",
            "phase": "checking",
            "current_step": "resume-step",
            "session_id": "s1",
        },
        "integrity": {"drift_detected": False},
    }
    manager.state_rebuilder = DummyStateRebuilder({"ok": True, "state": rebuilt_state})

    matched, state, integrity = manager._matching_active_context_from_rebuild(
        {"tx_id": 1, "ticket_id": "p4-t3"}
    )
    assert matched is None
    assert state == rebuilt_state
    assert integrity == {"drift_detected": False}


def test_emit_tx_begin_with_context_uses_rebuilt_state_when_materialized_state_missing():
    class RebuiltStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.append_and_save_calls = []
            self.append_calls = []

        def read_json_file(self, _path):
            return None

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True}

        def tx_event_append(self, **kwargs):
            self.append_calls.append(kwargs)
            return {"ok": True}

    rebuilt_state = {
        "active_tx": {
            "tx_id": 0,
            "ticket_id": "none",
            "status": "planned",
            "phase": "planned",
            "current_step": "none",
            "session_id": "",
        },
        "integrity": {"drift_detected": False},
    }
    state_store = RebuiltStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuilt_state}),
    )

    manager._emit_tx_begin_with_context(
        {
            "tx_id": 3,
            "ticket_id": "p4-t3",
            "phase": "checking",
            "step_id": "commit",
            "session_id": "s3",
        }
    )

    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_calls == []
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["tx_id"] == 3
    assert saved_state["active_tx"]["ticket_id"] == "p4-t3"
    assert saved_state["active_tx"]["status"] == "in-progress"
    assert saved_state["active_tx"]["phase"] == "in-progress"
    assert saved_state["active_tx"]["current_step"] == "none"
    assert saved_state["active_tx"]["session_id"] == "s3"
    assert saved_state["active_tx"]["verify_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved_state["active_tx"]["commit_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved_state["active_tx"]["file_intents"] == []
    assert saved_state["status"] == "in-progress"
    assert saved_state["next_action"] == "tx.verify.start"
    assert saved_state["verify_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved_state["commit_state"] == {
        "status": "not_started",
        "last_result": None,
    }
    assert saved_state["semantic_summary"] == "Transaction started"


def test_emit_tx_begin_with_context_falls_back_to_append_when_rebuilt_state_has_no_active_tx():
    class AppendOnlyStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.appended = []
            self.append_and_save_calls = []

        def read_json_file(self, _path):
            return None

        def tx_event_append(self, **kwargs):
            self.appended.append(kwargs)
            return {"ok": True}

        def tx_event_append_and_state_save(self, **kwargs):
            self.append_and_save_calls.append(kwargs)
            return {"ok": True}

    state_store = AppendOnlyStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder(
            {"ok": True, "state": {"integrity": {"drift_detected": False}}}
        ),
    )

    manager._emit_tx_begin_with_context(
        {
            "tx_id": 4,
            "ticket_id": "p4-t4",
            "phase": "verified",
            "step_id": "commit",
            "session_id": "s4",
        }
    )

    assert state_store.appended == []
    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_and_save_calls[0]["event_type"] == "tx.begin"
    assert state_store.append_and_save_calls[0]["ticket_id"] == "p4-t4"
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["tx_id"] == 4
    assert saved_state["active_tx"]["ticket_id"] == "p4-t4"
    assert saved_state["active_tx"]["status"] == "in-progress"
    assert saved_state["active_tx"]["phase"] == "in-progress"
    assert saved_state["active_tx"]["current_step"] == "none"
    assert saved_state["active_tx"]["session_id"] == "s4"
    assert saved_state["status"] == "in-progress"
    assert saved_state["next_action"] == "tx.verify.start"
    assert saved_state["semantic_summary"] == "Transaction started"


def test_ensure_tx_begin_blocks_invalid_rebuild_snapshot_when_materialized_missing():
    class MissingActiveTxStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.saved_states = []

        def read_json_file(self, _path):
            return {}

        def read_last_json_line(self, _path):
            return None

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

    rebuilt_state = {
        "active_tx": {
            "tx_id": 11,
            "ticket_id": "p4-t3",
            "status": "checking",
            "phase": "checking",
            "current_step": "resume-step",
            "session_id": "s1",
        },
        "integrity": {"drift_detected": False},
    }
    state_store = MissingActiveTxStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuilt_state}),
    )
    manager._load_tx_context = lambda: {
        "tx_id": 1,
        "ticket_id": "p4-t3",
        "phase": "checking",
        "step_id": "commit",
        "session_id": "s1",
    }

    with pytest.raises(RuntimeError) as exc_info:
        manager._ensure_tx_begin()

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "invalid_ordering"
    assert (
        payload["reason"]
        == "helper bootstrap blocked because rebuilt canonical state is not a valid exact-resume snapshot"
    )


def test_ensure_tx_begin_returns_when_rebuild_has_no_matching_active_context():
    class NoOpStateStore(DummyStateStore):
        def __init__(self):
            super().__init__()
            self.saved_states = []
            self.appended = []

        def read_json_file(self, _path):
            return None

        def read_last_json_line(self, _path):
            return None

        def tx_state_save(self, state):
            self.saved_states.append(state)
            return {"ok": True}

        def tx_event_append(self, **kwargs):
            self.appended.append(kwargs)
            return {"ok": True}

    rebuilt_state = {
        "active_tx": {
            "tx_id": 2,
            "ticket_id": "p4-t9",
            "status": "checking",
            "phase": "checking",
            "current_step": "resume-step",
            "next_action": "tx.verify.start",
            "session_id": "s2",
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
        "status": "checking",
        "next_action": "tx.verify.start",
        "verify_state": {"status": "not_started", "last_result": None},
        "commit_state": {"status": "not_started", "last_result": None},
        "semantic_summary": "Resume verification",
        "integrity": {"drift_detected": False},
    }
    state_store = NoOpStateStore()
    manager = CommitManager(
        DummyGitRepo(),
        DummyVerifyRunner({"ok": True}),
        state_store,
        DummyStateRebuilder({"ok": True, "state": rebuilt_state}),
    )
    emitted = []
    manager._emit_tx_begin_with_context = lambda context: emitted.append(context)

    manager._ensure_tx_begin()

    assert state_store.saved_states == []
    assert state_store.appended == []
    assert emitted == [
        {
            "tx_id": 1,
            "ticket_id": "p4-t3",
            "next_action": "tx.commit.start",
            "session_id": "resume",
        }
    ]
