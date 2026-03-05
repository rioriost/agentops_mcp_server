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
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        return ""

    def status_porcelain(self):
        return self._status_lines

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
        self.events = []
        self.repo_context = SimpleNamespace(
            journal=SimpleNamespace(exists=lambda: False),
            snapshot=SimpleNamespace(name="snapshot.json"),
            get_repo_root=lambda: "/tmp",
        )

    def journal_safe(self, kind, payload):
        self.events.append((kind, payload))

    def snapshot_save(self, **_kwargs):
        return {"ok": True}

    def checkpoint_update(self, **_kwargs):
        return {"ok": True}

    def read_json_file(self, _path):
        return None


class DummyStateRebuilder:
    def read_journal_events(self, start_seq=0):
        return {"events": [], "invalid_lines": 0, "last_seq": start_seq}

    def replay_events_to_state(
        self,
        snapshot_state=None,
        events=None,
        preferred_session_id=None,
        invalid_lines=0,
    ):
        return {}

    def rotate_journal_if_prev_week(self):
        return {"rotated": False}


def _build_manager(status_lines=None, verify_result=None):
    git_repo = DummyGitRepo(status_lines=status_lines)
    verify_runner = DummyVerifyRunner(verify_result or {"ok": True})
    state_store = DummyStateStore()
    state_rebuilder = DummyStateRebuilder()
    manager = CommitManager(git_repo, verify_runner, state_store, state_rebuilder)
    return manager, git_repo, verify_runner, state_store


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


def test_post_commit_snapshot_checkpoint_logs_skip(monkeypatch):
    manager, *_ = _build_manager()
    monkeypatch.setattr(
        manager, "_auto_snapshot_checkpoint_after_commit", lambda: {"ok": False}
    )

    manager._post_commit_snapshot_checkpoint()

    assert manager.state_store.events
    kind, payload = manager.state_store.events[0]
    assert kind == "error"
    assert payload["message"] == "auto snapshot/checkpoint skipped"


def test_post_commit_snapshot_checkpoint_logs_failure(monkeypatch):
    manager, *_ = _build_manager()

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(manager, "_auto_snapshot_checkpoint_after_commit", boom)

    manager._post_commit_snapshot_checkpoint()

    assert manager.state_store.events
    kind, payload = manager.state_store.events[0]
    assert kind == "error"
    assert payload["message"] == "auto snapshot/checkpoint failed"


def test_run_git_commit_records_commit_end(monkeypatch):
    manager, git_repo, *_ = _build_manager()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    called = {"post": False}

    def mark_post():
        called["post"] = True

    monkeypatch.setattr(manager, "_post_commit_snapshot_checkpoint", mark_post)

    sha, summary = manager._run_git_commit("msg")

    assert (sha, summary) == ("abc123", "diff")
    assert called["post"] is True

    commit_events = [
        payload for kind, payload in manager.state_store.events if kind == "commit.end"
    ]
    assert commit_events
    assert commit_events[0]["ok"] is True
    assert commit_events[0]["sha"] == "abc123"


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


def test_repo_commit_verify_failure_raises():
    manager, *_ = _build_manager(
        status_lines=[" M file.txt"],
        verify_result={"ok": False, "returncode": 1, "stderr": "nope", "stdout": ""},
    )

    with pytest.raises(RuntimeError, match="verify failed"):
        manager.repo_commit(run_verify=True)


def test_auto_snapshot_checkpoint_after_commit(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    manager = CommitManager(
        DummyGitRepo(), DummyVerifyRunner({"ok": True}), state_store, state_rebuilder
    )

    state_store.journal_append(
        kind="session.start",
        payload={"note": "start"},
        session_id="s1",
        event_id="evt-1",
    )

    result = manager._auto_snapshot_checkpoint_after_commit()

    assert result["ok"] is True
    assert result["snapshot"]["ok"] is True
    assert result["checkpoint"]["ok"] is True
    assert result["last_applied_seq"] >= 1


def test_auto_snapshot_checkpoint_after_commit_no_journal(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    manager = CommitManager(
        DummyGitRepo(), DummyVerifyRunner({"ok": True}), state_store, state_rebuilder
    )

    result = manager._auto_snapshot_checkpoint_after_commit()

    assert result["ok"] is False
    assert result["reason"] == "journal not found"


def test_auto_snapshot_checkpoint_after_commit_with_snapshot_only(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)
    manager = CommitManager(
        DummyGitRepo(), DummyVerifyRunner({"ok": True}), state_store, state_rebuilder
    )

    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text("", encoding="utf-8")

    state_store.snapshot_save(
        state={"session_id": "s1"}, session_id="s1", last_applied_seq=0
    )

    result = manager._auto_snapshot_checkpoint_after_commit()

    assert result["ok"] is True
    assert result["events_applied"] == 0


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
