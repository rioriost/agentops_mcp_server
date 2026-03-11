import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentops_mcp_server.ops_tools import OpsTools
from agentops_mcp_server.repo_tools import RepoTools
from agentops_mcp_server.workflow_response import (
    build_success_response,
    canonical_idle_baseline,
    is_canonical_idle_baseline,
    is_valid_active_exact_resume_tx_state,
    is_valid_exact_resume_tx_state,
)


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
    tx_id=1,
    ticket_id="p1-t1",
    status="in-progress",
    phase="in-progress",
    current_step="p1-t1",
    session_id="s1",
    verify_status="not_started",
    commit_status="not_started",
    next_action="tx.begin",
    semantic_summary="Active transaction",
    integrity=None,
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
        },
        "status": status,
        "next_action": next_action,
        "verify_state": {"status": verify_status, "last_result": None},
        "commit_state": {"status": commit_status, "last_result": None},
        "semantic_summary": semantic_summary,
        "integrity": integrity if integrity is not None else {"drift_detected": False},
    }


def _idle_state(next_action="tx.begin", integrity=None):
    baseline = canonical_idle_baseline(
        integrity=integrity if integrity is not None else {}
    )
    baseline["next_action"] = next_action
    return baseline


def test_load_resume_state_rejects_idle_state_with_noncanonical_next_action():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner()
    state_store = DummyStateStore(_idle_state(next_action="tx.verify.start"))
    state_rebuilder = DummyStateRebuilder(result={"ok": False})
    tools = RepoTools(git_repo, verify_runner, state_store, state_rebuilder)

    with pytest.raises(ValueError) as excinfo:
        tools._load_resume_state()

    failure = json.loads(str(excinfo.value))
    assert failure["ok"] is False
    assert failure["error_code"] == "invalid_ordering"
    assert (
        failure["reason"]
        == "resume blocked because materialized canonical state is malformed"
    )
    assert failure["recommended_next_tool"] == "ops_capture_state"


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
    state = _active_tx()

    assert is_valid_active_exact_resume_tx_state(state) is True
    assert is_valid_exact_resume_tx_state(state) is True

    invalid_state = {
        **state,
        "next_action": "",
    }

    assert is_valid_active_exact_resume_tx_state(invalid_state) is False
    assert is_valid_exact_resume_tx_state(invalid_state) is False


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


def _assert_helper_guidance(
    result,
    *,
    expected_status,
    expected_phase,
    expected_tx_status=None,
    expected_tx_phase=None,
):
    assert result["canonical_status"] == expected_status
    assert result["canonical_phase"] == expected_phase
    assert result["tx_status"] == (
        expected_status if expected_tx_status is None else expected_tx_status
    )
    assert result["tx_phase"] == (
        expected_phase if expected_tx_phase is None else expected_tx_phase
    )
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


def test_repo_verify_delegates_without_transaction_context():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tools = RepoTools(git_repo, verify_runner)

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    _assert_helper_guidance(result, expected_status="", expected_phase="")
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
    assert verify_runner.calls == [5]


def test_repo_verify_success_guidance_is_internally_consistent():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": True, "returncode": 0, "stdout": "ok", "stderr": ""}
    )
    tx_state = _active_tx(
        status="checking",
        phase="checking",
        current_step="p1-t1",
        next_action="tx.verify.start",
        verify_status="not_started",
        commit_status="not_started",
    )
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    _assert_helper_guidance(
        result,
        expected_status="checking",
        expected_phase="checking",
    )
    _assert_nonterminal_guidance_consistency(result)
    assert result["next_action"] == "tx.verify.start"
    assert result["followup_tool"] is None
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "p1-t1"
    assert result["active_tx"]["status"] == "verified"
    assert result["active_tx"]["verify_state"]["status"] == "passed"


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
    assert tools._load_tx_context() == {
        "tx_id": 1,
        "ticket_id": "none",
        "session_id": "s1",
        "next_action": "tx.begin",
    }

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state=_active_tx(session_id=""),
        ),
    )
    assert tools._load_tx_context() == {
        "tx_id": 1,
        "ticket_id": "p1-t1",
        "session_id": "resume",
        "next_action": "tx.begin",
    }


def test_load_tx_context_returns_none_when_materialized_next_action_is_blank():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": " p1-t1 ",
                    "status": "in-progress",
                    "phase": "in-progress",
                    "current_step": "",
                    "session_id": " ",
                },
                "status": "in-progress",
                "next_action": "",
                "verify_state": {"status": "not_started", "last_result": None},
                "commit_state": {"status": "not_started", "last_result": None},
                "semantic_summary": "resume me",
            }
        ),
        DummyStateRebuilder(
            result=_active_tx(
                status="checking",
                phase="checking",
                current_step="step-1",
                session_id="",
                next_action="tx.commit.start",
                semantic_summary="rebuilt active transaction",
            )
        ),
    )

    assert tools._load_tx_context() is None


def test_emit_tx_event_returns_none_without_context():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    assert tools._emit_tx_event(event_type="tx.verify.start", payload={}) is None


def test_load_tx_context_uses_top_level_next_action():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p1-t1",
                    "status": "checking",
                    "phase": "checking",
                    "current_step": "step-1",
                    "session_id": "s1",
                },
                "status": "checking",
                "next_action": "tx.commit.start",
                "verify_state": {"status": "running", "last_result": None},
                "commit_state": {"status": "not_started", "last_result": None},
                "semantic_summary": "checking exact active tx",
            }
        ),
    )

    assert tools._load_tx_context() == {
        "tx_id": 1,
        "ticket_id": "p1-t1",
        "session_id": "s1",
        "next_action": "tx.commit.start",
    }


def test_load_tx_context_returns_none_when_next_action_missing():
    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": 1,
                    "ticket_id": "p1-t1",
                    "status": "checking",
                    "phase": "checking",
                    "current_step": None,
                    "session_id": "s1",
                }
            }
        ),
    )

    assert tools._load_tx_context() is None


def test_emit_tx_event_preserves_exact_active_identity():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            status="in-progress",
            phase="in-progress",
            current_step="current-step",
            next_action="tx.verify.start",
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
    assert saved_state["active_tx"]["tx_id"] == 1
    assert saved_state["active_tx"]["ticket_id"] == "p1-t1"
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["phase"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "verify"
    assert saved_state["active_tx"]["verify_state"]["status"] == "failed"
    assert saved_state["active_tx"]["semantic_summary"] == "Verification failed"
    assert saved_state["active_tx"]["next_action"] == "fix and re-verify"


def test_emit_tx_event_uses_rebuilder_state_when_materialized_state_missing():
    state_store = DummyStateStore(tx_state=None)
    rebuilt_state = _active_tx(
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        next_action="tx.verify.start",
        semantic_summary="rebuilt active transaction",
    )
    state_rebuilder = DummyStateRebuilder(result={"ok": True, "state": rebuilt_state})
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
    saved = state_store.append_and_save_calls[0]["state"]
    assert saved["active_tx"]["tx_id"] == 1
    assert saved["active_tx"]["ticket_id"] == "p1-t1"
    assert saved["active_tx"]["status"] == "checking"
    assert saved["active_tx"]["phase"] == "checking"
    assert saved["active_tx"]["current_step"] == "verify-step"
    assert saved["active_tx"]["verify_state"]["status"] == "running"


def test_workflow_guidance_uses_success_response_shape():
    tx_state = _active_tx(
        status="verified",
        phase="verified",
        current_step="verify-step",
        verify_status="passed",
        commit_status="not_started",
        next_action="tx.commit.start",
    )
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


def test_emit_tx_event_uses_materialized_state_when_rebuilder_fails():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            status="checking",
            phase="checking",
            current_step="verify-step",
            next_action="tx.verify.pass",
            semantic_summary="verification running",
        )
    )
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
    saved = state_store.append_and_save_calls[0]["state"]
    assert saved["active_tx"]["status"] == "verified"
    assert saved["active_tx"]["verify_state"]["status"] == "passed"
    assert saved["active_tx"]["semantic_summary"] == "Verification passed"
    assert saved["active_tx"]["next_action"] == "tx.commit.start"


def test_emit_tx_event_uses_append_when_materialized_state_disappears_after_context_load():
    state_store = DummyStateStore(
        tx_state=_active_tx(
            status="checking",
            phase="checking",
            current_step="verify-step",
            next_action="tx.verify.pass",
            semantic_summary="verification running",
        )
    )
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
    assert len(state_store.append_calls) == 1
    assert state_store.append_and_save_calls == []
    assert state_store.append_calls[0]["event_type"] == "tx.verify.pass"


def test_emit_tx_event_rebuilds_when_materialized_state_lacks_required_contract():
    state_store = DummyStateStore(
        tx_state={
            "active_tx": {
                "tx_id": 1,
                "ticket_id": "p1-t1",
                "status": "checking",
                "phase": "checking",
                "current_step": "verify-step",
                "session_id": "s1",
            },
            "status": "checking",
            "next_action": "",
        }
    )
    rebuilt_state = _active_tx(
        status="checking",
        phase="checking",
        current_step="rebuilt-step",
        next_action="tx.verify.pass",
        semantic_summary="rebuilt exact active tx",
    )
    state_rebuilder = DummyStateRebuilder(result={"ok": True, "state": rebuilt_state})
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

    assert result == {"ok": True, "event_type": "tx.verify.pass"}
    assert len(state_store.append_and_save_calls) == 1
    saved = state_store.append_and_save_calls[0]["state"]
    assert saved["active_tx"]["tx_id"] == 1
    assert saved["active_tx"]["ticket_id"] == "p1-t1"
    assert saved["active_tx"]["status"] == "verified"


def test_repo_verify_with_active_tx_exposes_helper_guidance():
    tx_state = _active_tx(
        status="in-progress",
        phase="in-progress",
        current_step="verify-step",
        next_action="tx.verify.start",
    )
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
        expected_status="in-progress",
        expected_phase="in-progress",
    )
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "p1-t1"
    assert result["current_step"] is None
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["integrity_status"] == "ok"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx"]["tx_id"] == 1
    assert result["active_tx"]["ticket_id"] == "p1-t1"
    assert result["active_tx"]["status"] == "verified"
    assert result["active_tx"]["phase"] == "verified"
    assert result["active_tx"]["current_step"] == "verify"
    assert result["active_tx"]["verify_state"]["status"] == "passed"
    assert result["active_tx"]["semantic_summary"] == "Verification passed"
    assert result["active_tx"]["next_action"] == "tx.commit.start"
    assert verify_runner.calls == [7]


def test_repo_verify_failed_result_preserves_helper_guidance():
    tx_state = _active_tx(
        status="in-progress",
        phase="in-progress",
        current_step="verify-step",
        next_action="tx.verify.start",
    )
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
        expected_status="in-progress",
        expected_phase="in-progress",
    )
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "p1-t1"
    assert result["current_step"] is None
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["integrity_status"] == "ok"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    assert result["active_tx"]["tx_id"] == 1
    assert result["active_tx"]["ticket_id"] == "p1-t1"
    assert result["active_tx"]["status"] == "checking"
    assert result["active_tx"]["phase"] == "checking"
    assert result["active_tx"]["current_step"] == "verify"
    assert result["active_tx"]["verify_state"]["status"] == "failed"
    assert result["active_tx"]["semantic_summary"] == "Verification failed"
    assert result["active_tx"]["next_action"] == "fix and re-verify"
    assert verify_runner.calls == [11]


def test_repo_verify_records_failure_event_when_verify_fails():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(
        result={"ok": False, "returncode": 1, "stdout": "", "stderr": "boom"}
    )
    state_store = DummyStateStore(tx_state=_active_tx(next_action="tx.verify.start"))
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=9)

    assert result["ok"] is False
    _assert_helper_guidance(
        result, expected_status="in-progress", expected_phase="in-progress"
    )
    assert result["next_action"] == "tx.verify.start"
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


def test_repo_verify_rejects_terminal_transaction():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tx_state = {
        "status": "done",
        "next_action": "tx.end.done",
        "verify_state": {"status": "passed", "last_result": None},
        "commit_state": {"status": "passed", "last_result": None},
        "semantic_summary": "completed",
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p1-t1",
            "status": "done",
            "phase": "done",
            "current_step": "p1-t1",
            "session_id": "s1",
            "verify_state": {"status": "passed", "last_result": None},
            "commit_state": {"status": "passed", "last_result": None},
            "file_intents": [],
        },
        "integrity": {"drift_detected": False},
    }
    state_store = DummyStateStore(tx_state=tx_state)
    tools = RepoTools(git_repo, verify_runner, state_store, DummyStateRebuilder())

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    assert verify_runner.calls == [5]
    assert state_store.append_and_save_calls == []


def test_load_resume_state_prefers_healthy_materialized_state_over_rebuild_candidate():
    materialized_state = _active_tx(
        tx_id=7,
        ticket_id="p2-t03",
        status="checking",
        phase="checking",
        current_step="materialized-step",
        next_action="tx.verify.pass",
        semantic_summary="materialized state wins",
    )
    rebuilt_state = _active_tx(
        tx_id=99,
        ticket_id="other-ticket",
        status="verified",
        phase="verified",
        current_step="rebuilt-step",
        next_action="tx.commit.start",
        semantic_summary="rebuilt state should not replace exact active tx",
    )

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(tx_state=materialized_state),
        DummyStateRebuilder(result={"ok": True, "state": rebuilt_state}),
    )

    result = tools._load_resume_state()

    assert result is materialized_state
    assert result["active_tx"]["tx_id"] == 7
    assert result["active_tx"]["ticket_id"] == "p2-t03"
    assert result["next_action"] == "tx.verify.pass"


def test_load_resume_state_falls_back_to_rebuild_only_when_materialized_state_incomplete():
    incomplete_materialized = {
        "active_tx": {
            "tx_id": 7,
            "ticket_id": "p2-t03",
            "status": "checking",
            "phase": "checking",
            "current_step": "materialized-step",
            "session_id": "s1",
        },
        "status": "checking",
        "next_action": "",
    }
    rebuilt_state = _active_tx(
        tx_id=7,
        ticket_id="p2-t03",
        status="checking",
        phase="checking",
        current_step="rebuilt-step",
        next_action="tx.verify.pass",
        semantic_summary="rebuilt exact active tx",
    )

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(tx_state=incomplete_materialized),
        DummyStateRebuilder(result={"ok": True, "state": rebuilt_state}),
    )

    result = tools._load_resume_state()

    assert result == rebuilt_state
    assert result["active_tx"]["tx_id"] == 7
    assert result["active_tx"]["ticket_id"] == "p2-t03"
    assert result["next_action"] == "tx.verify.pass"


def test_load_resume_state_does_not_use_drifted_rebuild_as_resume_replacement():
    incomplete_materialized = {
        "active_tx": {
            "tx_id": 7,
            "ticket_id": "p2-t03",
            "status": "checking",
            "phase": "checking",
            "current_step": "materialized-step",
            "session_id": "s1",
        },
        "status": "checking",
        "next_action": "",
    }
    rebuilt_state = _active_tx(
        tx_id=7,
        ticket_id="p2-t03",
        status="checking",
        phase="checking",
        current_step="rebuilt-step",
        next_action="tx.verify.pass",
        semantic_summary="drifted rebuild should not be trusted",
        integrity={"drift_detected": True},
    )

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(tx_state=incomplete_materialized),
        DummyStateRebuilder(result={"ok": True, "state": rebuilt_state}),
    )

    result = tools._load_resume_state()

    assert result["active_tx"] is None
    assert result["status"] is None
    assert result["next_action"] == "tx.begin"


def test_load_tx_context_preserves_exact_active_identity_from_rebuild_fallback():
    rebuilt_state = _active_tx(
        tx_id=41,
        ticket_id="p2-t03",
        status="checking",
        phase="checking",
        current_step="rebuilt-step",
        next_action="tx.verify.pass",
        semantic_summary="resume exact active transaction",
    )

    tools = RepoTools(
        DummyGitRepo(),
        DummyVerifyRunner(),
        DummyStateStore(
            tx_state={
                "active_tx": {
                    "tx_id": 41,
                    "ticket_id": "p2-t03",
                    "status": "checking",
                    "phase": "checking",
                    "current_step": "broken",
                    "session_id": "s1",
                },
                "status": "checking",
                "next_action": "",
            }
        ),
        DummyStateRebuilder(result={"ok": True, "state": rebuilt_state}),
    )

    assert tools._load_tx_context() == {
        "tx_id": 41,
        "ticket_id": "p2-t03",
        "session_id": "s1",
        "next_action": "tx.verify.pass",
    }


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
        "canonical_id": "",
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

    with pytest.raises(ValueError, match="resume_required"):
        ops._require_active_tx("p1-t1", allow_resume=True)

    assert ops._is_terminal_active_tx({"status": "done"}) is True
    assert ops._is_terminal_active_tx({"phase": "blocked"}) is False
    assert ops._is_terminal_active_tx({"_terminal": True}) is False
    assert (
        ops._is_terminal_active_tx({"status": "checking", "phase": "checking"}) is False
    )


def test_repo_commit_message_suggest_prefers_docs_when_only_docs_change():
    tools = RepoTools(DummyGitRepo(), DummyVerifyRunner())

    result = tools.repo_commit_message_suggest(diff="docs/guide.md\nREADME.md\n")

    assert result["files"] == ["docs/guide.md", "README.md"]
    assert result["suggestions"][0].startswith("docs:")
