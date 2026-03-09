from types import SimpleNamespace

import pytest

from agentops_mcp_server.repo_tools import RepoTools
from agentops_mcp_server.workflow_rules import canonical_workflow_rules


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


def _active_tx(
    *,
    tx_id="tx-1",
    ticket_id="p1-t1",
    status="in-progress",
    phase="in-progress",
    current_step="p1-t1",
    session_id="s1",
):
    return {
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": phase,
            "current_step": current_step,
            "session_id": session_id,
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        }
    }


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


def test_load_tx_context_returns_none_without_state_store():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    assert tools._load_tx_context() is None


def test_load_tx_context_returns_none_for_missing_or_invalid_identity_fields():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={"active_tx": {"tx_id": "none", "ticket_id": "p1-t1"}}
        ),
    )
    assert tools._load_tx_context() is None

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state=_active_tx(ticket_id="none", session_id="s1"),
        ),
    )
    assert tools._load_tx_context() is None

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state=_active_tx(session_id=""),
        ),
    )
    assert tools._load_tx_context() is None


def test_load_tx_context_defaults_blank_phase_and_step():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": " tx-1 ",
                    "ticket_id": " p1-t1 ",
                    "status": "",
                    "phase": "",
                    "current_step": "",
                    "session_id": " s1 ",
                }
            }
        ),
    )

    assert tools._load_tx_context() == {
        "tx_id": "tx-1",
        "ticket_id": "p1-t1",
        "session_id": "s1",
        "phase": "in-progress",
        "step_id": "verify",
    }


def test_emit_tx_event_returns_none_without_context():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    assert tools._emit_tx_event(event_type="tx.verify.start", payload={}) is None


def test_emit_tx_event_uses_rebuilder_state_when_materialized_state_missing():
    state_store = DummyStateStore(tx_state=None)
    state_rebuilder = DummyStateRebuilder(result={"ok": True, "state": _active_tx()})
    state_store.tx_state = _active_tx()
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": ".zed/scripts/verify"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.start"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["phase"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "verify-step"
    assert saved_state["active_tx"]["verify_state"]["status"] == "running"


def test_emit_tx_event_falls_back_to_append_when_rebuilder_drifts():
    state_store = DummyStateStore(tx_state=None)
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                **_active_tx(),
                "integrity": {"drift_detected": True},
            },
        }
    )
    state_store.tx_state = _active_tx()
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.fail",
        payload={"ok": False, "error": "bad"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_calls == []
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"]["status"] == "failed"
    assert saved_state["active_tx"]["phase"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "verify-step"


def test_emit_tx_event_updates_failure_state_on_materialized_tx():
    tx_state = _active_tx()
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(
        DummyGitRepo(), DummyVerifyRunner(), state_store, DummyStateRebuilder()
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.fail",
        payload={"ok": False, "error": "bad"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"]["status"] == "failed"
    assert saved_state["active_tx"]["semantic_summary"] == "Verification failed"
    assert saved_state["active_tx"]["next_action"] == "fix and re-verify"


def test_repo_verify_records_failure_event_when_verify_fails():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": False, "returncode": 1, "stdout": "", "stderr": "boom"}
    )
    state_store = DummyStateStore(tx_state=_active_tx())
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=9)

    assert result["ok"] is False
    assert verify_runner.calls == [9]
    assert [call["event_type"] for call in state_store.append_and_save_calls] == [
        "tx.verify.start",
        "tx.verify.fail",
    ]
    assert state_store.tx_state["active_tx"]["verify_state"]["status"] == "failed"
    assert state_store.tx_state["active_tx"]["next_action"] == "fix and re-verify"


def test_repo_verify_records_stdout_when_stderr_missing():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": False, "returncode": 2, "stdout": "stdout only", "stderr": ""}
    )
    state_store = DummyStateStore(tx_state=_active_tx())
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    tools.repo_verify(timeout_sec=3)

    fail_call = state_store.append_and_save_calls[-1]
    assert fail_call["event_type"] == "tx.verify.fail"
    assert fail_call["payload"]["error"] == "stdout only"


def test_repo_verify_records_default_error_when_outputs_are_blank():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": False, "returncode": 2, "stdout": "", "stderr": ""}
    )
    state_store = DummyStateStore(tx_state=_active_tx())
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    tools.repo_verify(timeout_sec=3)

    fail_call = state_store.append_and_save_calls[-1]
    assert fail_call["payload"]["error"] == "verify failed"


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


def test_session_capture_context_without_verify_omits_verify_result():
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

    context = tools.session_capture_context(run_verify=False)

    assert context["branch"] == "main"
    assert "verify" not in context
    assert verify_runner.calls == []


def test_repo_commit_message_suggest_uses_git_diff_when_diff_not_provided():
    mapping = {
        ("diff", "--name-only", "--cached"): "tests/test_repo_tools.py\n",
        ("diff", "--name-only"): "",
        ("diff_stat_cached",): "cached diff",
        ("diff_stat",): "unstaged diff",
    }
    git_repo = DummyGitRepo(mapping)
    tools = RepoTools(git_repo, DummyVerifyRunner())

    result = tools.repo_commit_message_suggest()

    assert result["diff"] == "cached diff"
    assert result["files"] == ["tests/test_repo_tools.py"]
    assert result["suggestions"][0].startswith("feat:")


def test_repo_commit_message_suggest_defaults_to_chore_for_unknown_files():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    result = tools.repo_commit_message_suggest(diff="notes/unknown.ext\n")

    assert result["files"] == ["notes/unknown.ext"]
    assert result["suggestions"][0].startswith("chore:")


def test_canonical_workflow_rules_export_contains_key_contract_sections():
    rules = canonical_workflow_rules()

    assert rules.endswith("\n")
    assert "# AgentOps (strict rules)" in rules
    assert "## Planning flow (convention)" in rules
    assert (
        "- Ticket artifacts are client-managed workflow convention, not mandatory server protocol."
        in rules
    )
    assert "- `tx.begin` before task lifecycle events" in rules
    assert (
        "- commit operations require a valid verify sequence and existing transaction context"
        in rules
    )
