from types import SimpleNamespace

import pytest

from agentops_mcp_server.repo_tools import RepoTools


class DummyGitRepo:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.calls = []

    def git(self, *args):
        self.calls.append(args)
        return self.mapping.get(args, "")

    def diff_stat(self):
        return self.mapping.get(("diff_stat",), "diff")

    def diff_stat_cached(self):
        return self.mapping.get(("diff_stat_cached",), "")


class DummyVerifyRunner:
    def __init__(self, result=None):
        self.result = result or {"ok": True}
        self.calls = []

    def run_verify(self, timeout_sec=None):
        self.calls.append(timeout_sec)
        return self.result


class DummyStateStore:
    def __init__(self, tx_state=None):
        self.repo_context = SimpleNamespace(
            tx_state="tx_state.json",
            verify=".zed/scripts/verify",
        )
        self.tx_state = tx_state
        self.append_and_save_calls = []
        self.append_calls = []

    def read_json_file(self, _path):
        return self.tx_state

    def tx_event_append_and_state_save(self, **kwargs):
        self.append_and_save_calls.append(kwargs)
        self.tx_state = kwargs["state"]
        return {"ok": True, "event_type": kwargs["event_type"]}

    def tx_event_append(self, **kwargs):
        self.append_calls.append(kwargs)
        return {"ok": True, "event_type": kwargs["event_type"]}


class DummyStateRebuilder:
    def __init__(self, result=None):
        self.result = result or {"ok": False}

    def rebuild_tx_state(self):
        return self.result


def test_repo_status_summary_collects_fields():
    mapping = {
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--short"): " M file.txt",
        ("log", "-1", "--oneline"): "abc123 msg",
        ("diff", "--name-only"): "file.txt",
        ("diff", "--name-only", "--cached"): "",
        ("diff_stat",): "diff",
        ("diff_stat_cached",): "cached",
    }
    git_repo = DummyGitRepo(mapping)
    verify_runner = DummyVerifyRunner()
    tools = RepoTools(git_repo, verify_runner)

    summary = tools.repo_status_summary()

    assert summary["branch"] == "main"
    assert summary["status"] == " M file.txt"
    assert summary["diff"] == "diff"
    assert summary["staged_diff"] == "cached"
    assert summary["last_commit"] == "abc123 msg"
    assert summary["files"]["unstaged"] == "file.txt"
    assert summary["files"]["staged"] == ""


@pytest.mark.parametrize(
    ("diff", "prefix"),
    [
        ("docs/readme.md\n", "docs"),
        ("tests/notes.md\n", "test"),
        ("src/agentops_mcp_server/main.py\n", "feat"),
        ("pyproject.toml\n", "chore"),
    ],
)
def test_repo_commit_message_suggest_prefix(diff, prefix):
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner()
    tools = RepoTools(git_repo, verify_runner)

    result = tools.repo_commit_message_suggest(diff=diff)

    assert result["files"]
    assert result["suggestions"][0].startswith(f"{prefix}:")


def test_repo_verify_delegates():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tools = RepoTools(git_repo, verify_runner)

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    assert verify_runner.calls == [5]


def test_repo_verify_records_canonical_tx_events_when_active_tx_exists():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
    )
    tx_state = {
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p1-t1",
            "status": "in-progress",
            "phase": "in-progress",
            "current_step": "p1-t1",
            "session_id": "s1",
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        }
    }
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=7)

    assert result["ok"] is True
    assert verify_runner.calls == [7]
    assert [call["event_type"] for call in state_store.append_and_save_calls] == [
        "tx.verify.start",
        "tx.verify.pass",
    ]
    assert state_store.tx_state["active_tx"]["verify_state"]["status"] == "passed"
    assert state_store.tx_state["active_tx"]["status"] == "verified"


def test_repo_verify_rejects_terminal_transaction():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tx_state = {
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p1-t1",
            "status": "done",
            "phase": "done",
            "current_step": "p1-t1",
            "session_id": "s1",
            "verify_state": {"status": "passed", "last_result": None},
            "commit_state": {"status": "passed", "last_result": None},
            "file_intents": [],
        }
    }
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    with pytest.raises(ValueError, match="cannot verify a terminal transaction"):
        tools.repo_verify(timeout_sec=5)

    assert verify_runner.calls == []
    assert state_store.append_and_save_calls == []


def test_session_capture_context_with_verify():
    git_repo = DummyGitRepo(
        {
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--short"): "",
            ("log", "-1", "--oneline"): "abc msg",
            ("diff", "--name-only"): "",
            ("diff", "--name-only", "--cached"): "",
            ("diff_stat",): "",
            ("diff_stat_cached",): "",
        }
    )
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tools = RepoTools(git_repo, verify_runner)

    context = tools.session_capture_context(run_verify=True)

    assert context["branch"] == "main"
    assert context["verify"]["ok"] is True
