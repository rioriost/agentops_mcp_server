import json
import subprocess
from types import SimpleNamespace

import pytest

from agentops_mcp_server.commit_manager import CommitManager
from agentops_mcp_server.repo_context import RepoContext
from agentops_mcp_server.state_rebuilder import StateRebuilder
from agentops_mcp_server.state_store import StateStore


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
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_verify(self, timeout_sec=None):
        self.calls.append(timeout_sec)
        return self.result


class DummyStateStore:
    def __init__(self):
        self.repo_context = SimpleNamespace(
            tx_state="tx_state.json",
            verify="verify",
            get_repo_root=lambda: "/tmp",
        )

    def read_json_file(self, _path):
        return None


class DummyStateRebuilder:
    pass


def _build_manager(status_lines=None, verify_result=None):
    git_repo = DummyGitRepo(status_lines=status_lines)
    verify_runner = DummyVerifyRunner(verify_result or {"ok": True})
    state_store = DummyStateStore()
    state_rebuilder = DummyStateRebuilder()
    manager = CommitManager(git_repo, verify_runner, state_store, state_rebuilder)
    return manager, git_repo, verify_runner, state_store


def _write_tx_state(state_store, tx_id="tx-1", ticket_id="p4-t3"):
    state = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": "in-progress",
            "phase": "in-progress",
            "current_step": "commit",
            "last_completed_step": "",
            "next_action": "tx.commit.start",
            "semantic_summary": "Ready to commit",
            "user_intent": None,
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
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
    manager, *_ = _build_manager(status_lines=[])
    result = manager.repo_commit(message="msg", files="auto", run_verify=False)
    assert result["ok"] is False
    assert result["reason"] == "no changes to commit"


def test_repo_commit_auto_message(monkeypatch):
    manager, git_repo, *_ = _build_manager(status_lines=[" M file.txt"])
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.repo_commit(message=None, files="auto", run_verify=False)

    assert result["ok"] is True
    assert result["message"] == "chore: update 1 file(s)"
    assert ("add", "-A") in git_repo.calls


def test_commit_if_verified_runs_verify(monkeypatch):
    manager, git_repo, verify_runner, *_ = _build_manager(
        status_lines=[" M file.txt"], verify_result={"ok": True}
    )
    monkeypatch.setattr(manager, "_run_git_commit", lambda msg: ("sha", "summary"))

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["sha"] == "sha"
    assert verify_runner.calls == [5]
    assert ("add", "-A") in git_repo.calls


def test_commit_if_verified_emits_tx_commit_events(tmp_path, monkeypatch):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    _write_tx_state(state_store)

    manager = CommitManager(
        DummyGitRepo(status_lines=[" M file.txt"]),
        DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    result = manager.commit_if_verified("message", timeout_sec=5)
    assert result["sha"] == "abc123"

    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = [event["event_type"] for event in events]
    event_by_type = {event["event_type"]: event for event in events}

    assert "tx.verify.start" in event_types
    assert "tx.verify.pass" in event_types
    assert "tx.commit.start" in event_types
    assert "tx.commit.done" in event_types
    assert (
        event_types.index("tx.verify.start")
        < event_types.index("tx.verify.pass")
        < event_types.index("tx.commit.start")
        < event_types.index("tx.commit.done")
    )

    verify_start = event_by_type["tx.verify.start"]
    verify_pass = event_by_type["tx.verify.pass"]
    commit_start = event_by_type["tx.commit.start"]
    commit_done = event_by_type["tx.commit.done"]

    assert verify_start["phase"] == "checking"
    assert "command" in verify_start["payload"]
    assert verify_pass["phase"] == "checking"
    assert verify_pass["payload"]["ok"] is True
    assert commit_start["phase"] == "verified"
    assert commit_start["payload"]["message"] == "message"
    assert commit_start["payload"]["branch"] == "main"
    assert commit_start["payload"]["diff_summary"] == "diff"
    assert commit_done["phase"] == "committed"
    assert commit_done["payload"]["sha"] == "abc123"
    assert commit_done["payload"]["branch"] == "main"
    assert commit_done["payload"]["diff_summary"] == "diff"

    last_seq = max(event["seq"] for event in events)
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["last_applied_seq"] == last_seq
    assert tx_state["integrity"]["rebuilt_from_seq"] == last_seq
    active_tx = tx_state["active_tx"]
    assert active_tx["verify_state"]["status"] == "passed"
    assert active_tx["commit_state"]["status"] == "passed"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"
    assert active_tx["next_action"] == "tx.end.done"


def test_repo_commit_verify_failure_raises():
    manager, *_ = _build_manager(
        status_lines=[" M file.txt"],
        verify_result={"ok": False, "returncode": 1, "stderr": "nope", "stdout": ""},
    )

    with pytest.raises(RuntimeError, match="verify failed"):
        manager.repo_commit(run_verify=True)


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
