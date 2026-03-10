from pathlib import Path
from types import SimpleNamespace

import pytest

from agentops_mcp_server.ops_tools import OpsTools
from agentops_mcp_server.repo_tools import RepoTools
from agentops_mcp_server.workflow_response import build_success_response


class FailingStateStore:
    def __init__(self, tx_state=None, *, exc=RuntimeError("boom")):
        self.repo_context = SimpleNamespace(
            tx_state="tx_state.json",
            verify=".zed/scripts/verify",
        )
        self.tx_state = tx_state
        self.exc = exc

    def read_json_file(self, _path):
        raise self.exc


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
    verify_status="not_started",
    commit_status="not_started",
):
    return {
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": phase,
            "current_step": current_step,
            "session_id": session_id,
            "verify_state": {"status": verify_status, "last_result": None},
            "commit_state": {"status": commit_status, "last_result": None},
            "file_intents": [],
        }
    }


class DummyOpsStateStore:
    def __init__(self, state):
        self._state = state

    def read_json_file(self, _path):
        return self._state


class DummyOpsRebuilder:
    def __init__(self, state):
        self._state = state

    def rebuild_tx_state(self):
        return {"ok": True, "state": self._state}


def _assert_helper_guidance(result, *, expected_status, expected_phase):
    assert result["canonical_status"] == expected_status
    assert result["canonical_phase"] == expected_phase
    assert result["tx_status"] == expected_status
    assert result["tx_phase"] == expected_phase
    assert "next_action" in result
    assert "terminal" in result
    assert "requires_followup" in result
    assert "followup_tool" in result
    assert "active_tx_id" in result
    assert "active_ticket_id" in result
    assert "current_step" in result
    assert "verify_status" in result
    assert "commit_status" in result
    assert "integrity_status" in result
    assert "can_start_new_ticket" in result
    assert "resume_required" in result
    assert "active_tx" in result


def _assert_nonterminal_guidance_consistency(result):
    assert result["terminal"] is False
    if result["followup_tool"] == "ops_end_task":
        assert result["next_action"] in {"tx.end.done", "tx.end.blocked"}
        assert result["requires_followup"] is True
    if result["active_tx_id"] is not None or result["active_ticket_id"] is not None:
        assert result["can_start_new_ticket"] is False
        assert result["resume_required"] is True


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
    _assert_helper_guidance(result, expected_status="", expected_phase="")
    assert result["next_action"] == ""
    assert result["terminal"] is False
    assert result["requires_followup"] is False
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
    assert verify_runner.calls == [5]


def test_repo_verify_success_guidance_is_internally_consistent():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
    )
    tx_state = {
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p1-t1",
            "status": "checking",
            "phase": "checking",
            "current_step": "p1-t1",
            "session_id": "s1",
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        }
    }
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    _assert_helper_guidance(
        result, expected_status="verified", expected_phase="verified"
    )
    _assert_nonterminal_guidance_consistency(result)
    assert result["next_action"] == "tx.commit.start"
    assert result["followup_tool"] is None
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "not_started"
    assert result["active_tx_id"] == "tx-1"
    assert result["active_ticket_id"] == "p1-t1"


def test_load_tx_context_returns_none_without_state_store():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    assert tools._load_tx_context() is None


def test_load_tx_context_returns_none_when_state_store_read_fails():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        FailingStateStore(),
    )

    with pytest.raises(RuntimeError, match="boom"):
        tools._load_tx_context()


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


def test_load_tx_context_defaults_phase_when_status_is_non_string():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": "tx-1",
                    "ticket_id": "p1-t1",
                    "status": None,
                    "phase": None,
                    "current_step": "step-1",
                    "session_id": "s1",
                }
            }
        ),
    )

    assert tools._load_tx_context() == {
        "tx_id": "tx-1",
        "ticket_id": "p1-t1",
        "session_id": "s1",
        "phase": "in-progress",
        "step_id": "step-1",
    }


def test_load_tx_context_defaults_step_when_current_step_is_non_string():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": "tx-1",
                    "ticket_id": "p1-t1",
                    "status": "checking",
                    "phase": "checking",
                    "current_step": None,
                    "session_id": "s1",
                }
            }
        ),
    )

    assert tools._load_tx_context() == {
        "tx_id": "tx-1",
        "ticket_id": "p1-t1",
        "session_id": "s1",
        "phase": "checking",
        "step_id": "verify",
    }


def test_emit_tx_event_preserves_existing_step_and_phase_without_overrides():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            status="in-progress",
            phase="in-progress",
            current_step="current-step",
        )
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        DummyStateRebuilder(),
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.fail",
        payload={"error": "verify failed"},
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["status"] == "in-progress"
    assert saved_state["active_tx"]["phase"] == "in-progress"
    assert saved_state["active_tx"]["current_step"] == "current-step"
    assert saved_state["active_tx"]["verify_state"]["status"] == "failed"
    assert saved_state["active_tx"]["next_action"] == "fix and re-verify"


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


def test_workflow_guidance_uses_success_response_shape():
    tx_state = _active_tx(
        status="verified",
        phase="verified",
        current_step="verify-step",
        verify_status="passed",
        commit_status="not_started",
    )
    tx_state["integrity"] = {"drift_detected": False}
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        DummyStateRebuilder(),
    )

    guidance = tools._workflow_guidance()

    expected = build_success_response(tx_state=tx_state)
    assert guidance["canonical_status"] == expected["canonical_status"]
    assert guidance["canonical_phase"] == expected["canonical_phase"]
    assert guidance["next_action"] == expected["next_action"]
    assert guidance["terminal"] == expected["terminal"]
    assert guidance["requires_followup"] == expected["requires_followup"]
    assert guidance["followup_tool"] == expected["followup_tool"]
    assert guidance["active_tx_id"] == expected["active_tx_id"]
    assert guidance["active_ticket_id"] == expected["active_ticket_id"]
    assert guidance["current_step"] == expected["current_step"]
    assert guidance["verify_status"] == expected["verify_status"]
    assert guidance["commit_status"] == expected["commit_status"]
    assert guidance["integrity_status"] == expected["integrity_status"]
    assert guidance["can_start_new_ticket"] == expected["can_start_new_ticket"]
    assert guidance["resume_required"] == expected["resume_required"]
    assert guidance["active_tx"] == tx_state["active_tx"]


def test_workflow_guidance_defaults_to_empty_shape_without_state_store():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    guidance = tools._workflow_guidance()

    assert guidance == {
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


def test_emit_tx_event_uses_materialized_state_when_rebuilder_fails():
    state_store = DummyStateStore(tx_state=_active_tx())
    state_rebuilder = DummyStateRebuilder(result={"ok": False})
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
        phase_override="verified",
    )

    assert result == {"ok": True, "event_type": "tx.verify.pass"}
    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_calls == []
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"]["status"] == "passed"
    assert saved_state["active_tx"]["semantic_summary"] == "Verification passed"
    assert saved_state["active_tx"]["next_action"] == "tx.commit.start"


def test_emit_tx_event_returns_none_when_context_disappears_before_append_fallback():
    state_store = DummyStateStore(tx_state=None)
    state_rebuilder = DummyStateRebuilder(result={"ok": False})
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    state_store.tx_state = _active_tx()
    original_read_json_file = state_store.read_json_file

    def read_json_file_once(_path):
        if state_store.tx_state is not None:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_once

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
        phase_override="verified",
    )

    assert result is None
    assert state_store.append_and_save_calls == []
    assert state_store.append_calls == []


def test_emit_tx_event_uses_append_when_materialized_state_disappears_after_context_load():
    state_store = DummyStateStore(tx_state=_active_tx())
    state_rebuilder = DummyStateRebuilder(result={"ok": False})
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_with_late_loss(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_with_late_loss

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
        phase_override="verified",
    )

    assert result == {"ok": True, "event_type": "tx.verify.pass"}
    assert state_store.append_and_save_calls == []
    assert len(state_store.append_calls) == 1
    assert state_store.append_calls[0]["event_type"] == "tx.verify.pass"


def test_emit_tx_event_returns_none_when_materialized_state_lacks_active_tx():
    state_store = DummyStateStore(tx_state={})
    state_rebuilder = DummyStateRebuilder(result={"ok": True, "state": _active_tx()})
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
        phase_override="verified",
        step_id_override="verify-step",
    )

    assert result is None
    assert state_store.append_and_save_calls == []
    assert state_store.append_calls == []


def test_repo_verify_with_active_tx_exposes_helper_guidance():
    tx_state = _active_tx(
        status="in-progress",
        phase="in-progress",
        current_step="verify-step",
    )
    tx_state["integrity"] = {"drift_detected": False}
    state_store = DummyStateStore(tx_state=tx_state)
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "verify ok"}
    )
    tools = RepoTools(
        DummyGitRepo(),
        verify_runner,
        state_store,
        DummyStateRebuilder(),
    )

    result = tools.repo_verify(timeout_sec=7)

    assert result["ok"] is True
    _assert_helper_guidance(
        result,
        expected_status="verified",
        expected_phase="verified",
    )
    assert result["next_action"] == "tx.commit.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == "tx-1"
    assert result["active_ticket_id"] == "p1-t1"
    assert result["current_step"] == "verify-step"
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "not_started"
    assert result["integrity_status"] == "ok"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx"]["verify_state"]["status"] == "passed"
    assert verify_runner.calls == [7]


def test_repo_verify_failed_result_preserves_helper_guidance():
    tx_state = _active_tx(
        status="in-progress",
        phase="in-progress",
        current_step="verify-step",
    )
    tx_state["integrity"] = {"drift_detected": False}
    state_store = DummyStateStore(tx_state=tx_state)
    verify_runner = DummyVerifyRunner(
        result={"ok": False, "returncode": 2, "stderr": "verify failed"}
    )
    tools = RepoTools(
        DummyGitRepo(),
        verify_runner,
        state_store,
        DummyStateRebuilder(),
    )

    result = tools.repo_verify(timeout_sec=11)

    assert result["ok"] is False
    _assert_helper_guidance(
        result,
        expected_status="checking",
        expected_phase="checking",
    )
    assert result["next_action"] == "fix and re-verify"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == "tx-1"
    assert result["active_ticket_id"] == "p1-t1"
    assert result["current_step"] == "verify-step"
    assert result["verify_status"] == "failed"
    assert result["commit_status"] == "not_started"
    assert result["integrity_status"] == "ok"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx"]["verify_state"]["status"] == "failed"
    assert verify_runner.calls == [11]


def test_emit_tx_event_uses_materialized_state_when_rebuilder_state_has_no_active_tx():
    state_store = DummyStateStore(tx_state=_active_tx())
    state_rebuilder = DummyStateRebuilder(result={"ok": True, "state": {}})
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
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    assert len(state_store.append_and_save_calls) == 1
    assert state_store.append_calls == []
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"]["status"] == "failed"
    assert saved_state["active_tx"]["semantic_summary"] == "Verification failed"
    assert saved_state["active_tx"]["next_action"] == "fix and re-verify"


def test_emit_tx_event_appends_when_rebuilder_integrity_is_not_a_dict():
    state_store = DummyStateStore(tx_state=None)
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                **_active_tx(),
                "integrity": "unexpected",
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    state_store.tx_state = _active_tx()
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_with_late_loss(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_with_late_loss

    result = tools._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": ".zed/scripts/verify"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.start"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"]["status"] == "running"
    assert saved_state["active_tx"]["next_action"] == "tx.verify.pass"


def test_emit_tx_event_rebuilder_branch_updates_start_state_directly():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            tx_id="tx-1",
            ticket_id="p1-t1",
            status="checking",
            phase="checking",
            current_step="step-1",
            session_id="s1",
        )
    )
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                "active_tx": {
                    "verify_state": {"status": "not_started", "last_result": None},
                    "commit_state": {"status": "not_started", "last_result": None},
                    "file_intents": [],
                },
                "integrity": {"drift_detected": False},
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_force_rebuild(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_force_rebuild

    result = tools._emit_tx_event(
        event_type="tx.verify.start",
        payload={"command": ".zed/scripts/verify"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.start"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["tx_id"] == "tx-1"
    assert saved_state["active_tx"]["ticket_id"] == "p1-t1"
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["phase"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "verify-step"
    assert saved_state["active_tx"]["session_id"] == "s1"
    assert saved_state["active_tx"]["verify_state"] == {
        "status": "running",
        "last_result": {"command": ".zed/scripts/verify"},
    }
    assert saved_state["active_tx"]["next_action"] == "tx.verify.pass"


def test_emit_tx_event_rebuilder_branch_updates_pass_state_directly():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            tx_id="tx-1",
            ticket_id="p1-t1",
            status="checking",
            phase="checking",
            current_step="step-1",
            session_id="s1",
        )
    )
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                "active_tx": {
                    "verify_state": {"status": "running", "last_result": None},
                    "commit_state": {"status": "not_started", "last_result": None},
                    "file_intents": [],
                },
                "integrity": {"drift_detected": False},
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_force_rebuild(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_force_rebuild

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
        phase_override="verified",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.pass"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"] == {
        "status": "passed",
        "last_result": {"ok": True},
    }
    assert saved_state["active_tx"]["semantic_summary"] == "Verification passed"
    assert saved_state["active_tx"]["next_action"] == "tx.commit.start"


def test_emit_tx_event_rebuilder_branch_updates_fail_state_directly():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            tx_id="tx-1",
            ticket_id="p1-t1",
            status="checking",
            phase="checking",
            current_step="step-1",
            session_id="s1",
        )
    )
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                "active_tx": {
                    "verify_state": {"status": "running", "last_result": None},
                    "commit_state": {"status": "not_started", "last_result": None},
                    "file_intents": [],
                },
                "integrity": {"drift_detected": False},
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_force_rebuild(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_force_rebuild

    result = tools._emit_tx_event(
        event_type="tx.verify.fail",
        payload={"ok": False, "error": "boom"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["verify_state"] == {
        "status": "failed",
        "last_result": {"ok": False, "error": "boom"},
    }
    assert saved_state["active_tx"]["semantic_summary"] == "Verification failed"
    assert saved_state["active_tx"]["next_action"] == "fix and re-verify"


def test_emit_tx_event_rebuilder_branch_defaults_blank_phase_and_step():
    state_store = DummyStateStore(
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
    )
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                "active_tx": {
                    "verify_state": {"status": "not_started", "last_result": None},
                    "commit_state": {"status": "not_started", "last_result": None},
                    "file_intents": [],
                }
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.pass",
        payload={"ok": True},
    )

    assert result == {"ok": True, "event_type": "tx.verify.pass"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"]["status"] == "in-progress"
    assert saved_state["active_tx"]["phase"] == "in-progress"
    assert saved_state["active_tx"]["current_step"] == "verify"
    assert saved_state["active_tx"]["verify_state"]["status"] == "passed"
    assert saved_state["active_tx"]["semantic_summary"] == "Verification passed"
    assert saved_state["active_tx"]["next_action"] == "tx.commit.start"


def test_emit_tx_event_rebuilder_branch_sets_failure_state_without_active_tx_dict():
    state_store = DummyStateStore(tx_state=None)
    state_store.tx_state = _active_tx()
    original_read_json_file = state_store.read_json_file
    call_count = {"count": 0}

    def read_json_file_with_late_loss(_path):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return original_read_json_file(_path)
        if call_count["count"] == 2:
            state_store.tx_state = None
            return None
        return original_read_json_file(_path)

    state_store.read_json_file = read_json_file_with_late_loss
    state_rebuilder = DummyStateRebuilder(
        result={
            "ok": True,
            "state": {
                "active_tx": "unexpected",
                "integrity": {"drift_detected": False},
            },
        }
    )
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        state_store,
        state_rebuilder,
    )

    result = tools._emit_tx_event(
        event_type="tx.verify.fail",
        payload={"ok": False, "error": "boom"},
        phase_override="checking",
        step_id_override="verify-step",
    )

    assert result == {"ok": True, "event_type": "tx.verify.fail"}
    assert len(state_store.append_and_save_calls) == 1
    saved_state = state_store.append_and_save_calls[0]["state"]
    assert saved_state["active_tx"] == "unexpected"


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
    _assert_helper_guidance(
        result, expected_status="checking", expected_phase="checking"
    )
    assert result["next_action"] == "fix and re-verify"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert verify_runner.calls == [9]
    assert [call["event_type"] for call in state_store.append_and_save_calls] == [
        "tx.verify.start",
        "tx.verify.fail",
    ]
    assert state_store.tx_state["active_tx"]["verify_state"]["status"] == "failed"
    assert state_store.tx_state["active_tx"]["next_action"] == "fix and re-verify"


def test_repo_verify_allows_blocked_phase_when_status_is_non_terminal():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "ok"}
    )
    tx_state = {
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p1-t1",
            "status": "verified",
            "phase": "blocked",
            "current_step": "p1-t1",
            "session_id": "s1",
            "verify_state": {"status": "passed", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        }
    }
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    _assert_helper_guidance(
        result, expected_status="verified", expected_phase="verified"
    )
    assert result["next_action"] == "tx.commit.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert verify_runner.calls == [5]
    assert [call["event_type"] for call in state_store.append_and_save_calls] == [
        "tx.verify.start",
        "tx.verify.pass",
    ]


def test_repo_verify_ignores_non_dict_active_tx_when_checking_terminal_state():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "verify ok", "stderr": ""}
    )
    state_store = DummyStateStore(tx_state={"active_tx": []})
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=8)

    assert result["ok"] is True
    _assert_helper_guidance(result, expected_status="", expected_phase="")
    assert result["next_action"] == ""
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None
    assert verify_runner.calls == [8]


def test_repo_verify_uses_stdout_fallback_on_success():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "", "stderr": ""}
    )
    state_store = DummyStateStore(tx_state=_active_tx())
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    tools.repo_verify(timeout_sec=4)

    success_call = state_store.append_and_save_calls[-1]
    assert success_call["event_type"] == "tx.verify.pass"
    assert success_call["payload"]["summary"] == "verify passed"


def test_repo_verify_without_state_store_delegates_directly_even_when_rebuilder_exists():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True, "returncode": 0})
    tools = RepoTools(git_repo, verify_runner, None, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=6)

    assert result["ok"] is True
    assert result["tx_status"] == ""
    assert result["tx_phase"] == ""
    assert result["next_action"] == ""
    assert result["terminal"] is False
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None
    assert verify_runner.calls == [6]


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
    assert result["tx_status"] == "verified"
    assert result["tx_phase"] == "verified"
    assert result["next_action"] == "tx.commit.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
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


def test_repo_verify_rejects_terminal_transaction_without_contradictory_guidance():
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


def test_repo_commit_message_suggest_prefers_feat_when_test_file_has_code_suffix():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    result = tools.repo_commit_message_suggest(
        diff="docs/guide.md\ntests/test_repo_tools.py\n"
    )

    assert result["files"] == ["docs/guide.md", "tests/test_repo_tools.py"]
    assert result["suggestions"][0].startswith("feat:")


def test_repo_commit_message_suggest_uses_unstaged_diff_when_cached_diff_missing():
    mapping = {
        ("diff", "--name-only", "--cached"): "",
        ("diff", "--name-only"): "docs/readme.md\n",
        ("diff_stat_cached",): "",
        ("diff_stat",): "unstaged diff",
    }
    git_repo = DummyGitRepo(mapping)
    tools = RepoTools(git_repo, DummyVerifyRunner())

    result = tools.repo_commit_message_suggest()

    assert result["diff"] == "unstaged diff"
    assert result["files"] == ["docs/readme.md"]
    assert result["suggestions"][0].startswith("docs:")


def test_rules_template_contains_key_contract_sections():
    rules = Path("src/agentops_mcp_server/rules_template.txt").read_text(
        encoding="utf-8"
    )


def test_rules_template_contains_key_contract_sections():
    rules = Path("src/agentops_mcp_server/rules_template.txt").read_text(
        encoding="utf-8"
    )

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


def test_ops_tools_helper_branches_cover_identifier_and_error_helpers():
    state = _active_tx()
    state["active_tx"]["verify_state"] = {
        "status": "failed",
        "last_result": {"error": "verify failed"},
    }
    state["active_tx"]["commit_state"] = {
        "status": "failed",
        "last_result": {"sha": "abc123", "summary": "commit summary"},
    }
    ops = OpsTools(
        repo_context=SimpleNamespace(tx_state="tx_state.json"),
        state_store=DummyOpsStateStore(state),
        state_rebuilder=DummyOpsRebuilder(state),
        git_repo=DummyGitRepo(),
    )

    assert ops._normalize_tx_identifier(None) == ""
    assert ops._normalize_tx_identifier(" none ") == ""
    assert ops._normalize_tx_identifier(" tx-1 ") == "tx-1"

    assert ops._active_tx_identity({"tx_id": "none", "ticket_id": " t-1 "}) == {
        "tx_id": "",
        "ticket_id": "t-1",
        "canonical_id": "t-1",
        "has_canonical_tx": False,
    }

    assert (
        ops._extract_last_error(
            {"last_result": {"error": "verify failed"}},
            {"last_result": {"error": "commit failed"}},
        )
        == "verify failed"
    )
    assert ops._extract_last_error({}, {"last_result": {"error": "commit failed"}}) == (
        "commit failed"
    )
    assert (
        ops._extract_last_commit(
            {"last_result": {"sha": "abc123", "summary": "commit summary"}}
        )
        == "abc123"
    )
    assert ops._extract_last_commit({"last_result": {"summary": "commit summary"}}) == (
        "commit summary"
    )


def test_ops_tools_require_active_tx_allow_resume_and_terminal_detection():
    state = _active_tx(status="checking", phase="checking")
    ops = OpsTools(
        repo_context=SimpleNamespace(tx_state="tx_state.json"),
        state_store=DummyOpsStateStore(state),
        state_rebuilder=DummyOpsRebuilder(state),
        git_repo=DummyGitRepo(),
    )

    active_tx, resolved_id = ops._require_active_tx("tx-1", allow_resume=True)
    assert active_tx["tx_id"] == "tx-1"
    assert resolved_id == "tx-1"

    assert ops._is_terminal_active_tx({"status": "done"}) is True
    assert ops._is_terminal_active_tx({"phase": "blocked"}) is True
    assert ops._is_terminal_active_tx({"_terminal": True}) is True
    assert (
        ops._is_terminal_active_tx({"status": "checking", "phase": "checking"}) is False
    )


def test_repo_commit_message_suggest_prefers_docs_when_only_docs_change():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    result = tools.repo_commit_message_suggest(diff="docs/guide.md\nREADME.md\n")

    assert result["files"] == ["docs/guide.md", "README.md"]
    assert result["suggestions"][0].startswith("docs:")
