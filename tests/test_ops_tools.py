import json

import pytest

from agentops_mcp_server.ops_tools import (
    OpsTools,
    build_compact_context,
    summarize_result,
    truncate_text,
)


class DummyGitRepo:
    def __init__(self, diff_value="diff", diff_error=None):
        self.diff_value = diff_value
        self.diff_error = diff_error

    def diff_stat(self):
        if self.diff_error is not None:
            raise self.diff_error
        return self.diff_value


def _build_ops_tools(repo_context, state_store, state_rebuilder, git_repo=None):
    return OpsTools(
        repo_context,
        state_store,
        state_rebuilder,
        git_repo or DummyGitRepo(),
    )


def _read_tx_events(repo_context):
    if not repo_context.tx_event_log.exists():
        return []
    return [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tx_event_types(repo_context):
    return [event["event_type"] for event in _read_tx_events(repo_context)]


def _write_tx_state(repo_context, state):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return state


def _active_tx_state(
    *,
    tx_id=1,
    ticket_id="p1-t1",
    status="in-progress",
    phase=None,
    current_step="task",
    next_action="tx.verify.start",
    semantic_summary="Entered step task",
    session_id="s1",
    verify_state=None,
    commit_state=None,
):
    resolved_phase = phase or status
    verify = verify_state or {"status": "not_started", "last_result": None}
    commit = commit_state or {"status": "not_started", "last_result": None}
    return {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": resolved_phase,
            "current_step": current_step,
            "last_completed_step": "",
            "next_action": next_action,
            "semantic_summary": semantic_summary,
            "user_intent": None,
            "session_id": session_id,
            "verify_state": verify,
            "commit_state": commit,
            "file_intents": [],
            "_last_event_seq": 0,
            "_terminal": status in {"done", "blocked"},
        },
        "status": status,
        "next_action": next_action,
        "semantic_summary": semantic_summary,
        "verify_state": verify,
        "commit_state": commit,
        "last_applied_seq": 0,
        "integrity": {
            "state_hash": "test-hash",
            "rebuilt_from_seq": 0,
            "drift_detected": False,
            "active_tx_source": "materialized",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }


def _seed_active_tx(repo_context, **overrides):
    state = _active_tx_state(**overrides)
    return _write_tx_state(repo_context, state)


def _begin_tx(
    state_store, state_rebuilder, tx_id=1, ticket_id="p1-t1", session_id="s1"
):
    state_store.repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    state_store.repo_context.tx_event_log.write_text("", encoding="utf-8")
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_event_append_and_state_save(
        tx_id=tx_id,
        ticket_id=ticket_id,
        event_type="tx.begin",
        phase="in-progress",
        step_id="none",
        actor={"tool": "test"},
        session_id=session_id,
        payload={"ticket_id": ticket_id, "ticket_title": ticket_id},
        state=rebuild["state"],
    )
    tx_state = json.loads(state_store.repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["status"] = "in-progress"
    tx_state["active_tx"]["phase"] = "in-progress"
    tx_state["active_tx"]["current_step"] = "task"
    tx_state["active_tx"]["next_action"] = "tx.verify.start"
    tx_state["active_tx"]["semantic_summary"] = f"Started transaction {ticket_id}"
    tx_state["active_tx"]["verify_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["status"] = "in-progress"
    tx_state["next_action"] = "tx.verify.start"
    tx_state["semantic_summary"] = f"Started transaction {ticket_id}"
    tx_state["verify_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["commit_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    integrity = tx_state.get("integrity")
    if isinstance(integrity, dict):
        integrity["active_tx_source"] = "materialized"
    state_store.tx_state_save(tx_state)


def _assert_workflow_guidance_fields(result, *, expected_status, expected_phase):
    assert result["ok"] is True
    assert result["canonical_status"] == expected_status
    assert result["canonical_phase"] == expected_phase
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
    assert "active_tx" in result
    assert isinstance(result["active_tx"], dict)


def test_truncate_text_handles_none_and_bounds():
    assert truncate_text(None) is None
    assert truncate_text("abc", limit=0) == ""
    assert truncate_text("abc", limit=10) == "abc"
    assert truncate_text("abcdef", limit=3) == "abc...(truncated)"


def test_build_compact_context_includes_only_present_fields():
    summary = build_compact_context(
        {
            "session_id": "s1",
            "current_phase": "checking",
            "current_task": "p1-t1",
            "last_action": "Ran verify",
            "next_step": "tx.commit.start",
            "verification_status": "passed",
            "last_commit": "",
            "last_error": "",
        },
        " file.py | 1 +\n 1 file changed, 1 insertion(+)",
        400,
    )

    assert "session_id: s1" in summary
    assert "current_phase: checking" in summary
    assert "current_task: p1-t1" in summary
    assert "last_action: Ran verify" in summary
    assert "next_step: tx.commit.start" in summary
    assert "verification_status: passed" in summary
    assert "diff_stat:" in summary
    assert "1 file changed" in summary
    assert "last_commit:" not in summary
    assert "last_error:" not in summary


def test_build_compact_context_falls_back_when_empty():
    assert build_compact_context({}, None, 200) == "no recent state available"


def test_summarize_result_preserves_small_payloads():
    payload = {"ok": True, "value": "small"}
    assert summarize_result(payload, limit=200) == payload


def test_summarize_result_truncates_large_payloads():
    payload = {"value": "x" * 500}
    result = summarize_result(payload, limit=60)

    assert result["truncated"] is True
    assert result["summary"].endswith("...(truncated)")


def test_ops_compact_context_defaults_and_includes_diff(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id="tx-1",
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        semantic_summary="Entered step resume-step",
    )
    git_repo = DummyGitRepo(
        diff_value=" file.py | 1 +\n 1 file changed, 1 insertion(+)"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder, git_repo)

    result = ops.ops_compact_context(max_chars=None, include_diff=True)

    assert result["ok"] is True
    assert result["max_chars"] == 800
    assert result["include_diff"] is True
    assert "current_phase: checking" in result["compact_context"]
    assert "current_task: p1-t1" in result["compact_context"]
    assert "last_action: Entered step resume-step" in result["compact_context"]
    assert "next_step: tx.verify.start" in result["compact_context"]
    assert "diff_stat:" in result["compact_context"]
    assert "1 file changed" in result["compact_context"]


def test_ops_compact_context_truncates_without_diff(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        semantic_summary="x" * 200,
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=20, include_diff=False)

    assert result["ok"] is True
    assert result["max_chars"] == 20
    assert result["include_diff"] is False
    assert result["compact_context"].endswith("...(truncated)")


def test_ops_handoff_export_writes_json(repo_context, state_store, state_rebuilder):
    _seed_active_tx(
        repo_context,
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        semantic_summary="Entered step review",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["wrote"] is True
    assert result["path"]
    payload = json.loads(repo_context.handoff.read_text(encoding="utf-8"))
    assert payload["current_task"] == "p1-t1"
    assert payload["last_action"] == "Entered step review"
    assert payload["next_step"] == "tx.verify.start"
    assert "compact_context" in payload


def test_ops_handoff_export_defaults_to_tx_begin_without_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["current_task"] == ""
    assert result["handoff"]["next_step"] == "tx.begin"


def test_ops_resume_brief_allows_new_ticket_when_idle(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=200)

    assert result["ok"] is True
    assert "resume_brief:" in result["brief"]
    assert "- can_start_new_ticket: yes" in result["brief"]


def test_ops_resume_brief_requires_resuming_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=5,
        ticket_id="p2-t3",
        status="checking",
        phase="checking",
        current_step="p2-t3",
        next_action="tx.commit.start",
        semantic_summary="Verification passed",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    assert "- active_ticket: p2-t3" in result["brief"]
    assert "- active_status: checking" in result["brief"]
    assert "- required_next_action: tx.commit.start" in result["brief"]
    assert "- can_start_new_ticket: no" in result["brief"]


def test_ops_start_task_bootstraps_begin_and_enters_step(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(
        title="Implement workflow coverage",
        task_id="p3-t1",
        session_id="s1",
        agent_id="agent-test",
        status="in-progress",
    )

    _assert_workflow_guidance_fields(
        result,
        expected_status="in-progress",
        expected_phase="in-progress",
    )
    assert result["active_ticket_id"] == "p3-t1"
    assert result["current_step"] == "p3-t1"
    assert _tx_event_types(repo_context) == ["tx.begin", "tx.step.enter"]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["ticket_id"] == "p3-t1"
    assert tx_state["active_tx"]["session_id"] == "s1"


def test_ops_start_task_requires_task_id_when_bootstrapping(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="task_id is required to bootstrap tx.begin"):
        ops.ops_start_task(title="Missing task id")


def test_ops_update_task_rejects_terminal_statuses(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(state_store, state_rebuilder, tx_id=1, ticket_id="p4-t1", session_id="s1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="use ops_end_task for terminal done state"):
        ops.ops_update_task(status="done", task_id="p4-t1", session_id="s1")

    with pytest.raises(ValueError, match="use ops_end_task for terminal blocked state"):
        ops.ops_update_task(status="blocked", task_id="p4-t1", session_id="s1")


def test_ops_update_task_updates_phase_and_records_user_intent(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(state_store, state_rebuilder, tx_id=9, ticket_id="p4-t2", session_id="s1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_update_task(
        status="checking",
        note="Compare acceptance criteria",
        task_id="p4-t2",
        session_id="s1",
        user_intent="resume p4-t2",
    )

    _assert_workflow_guidance_fields(
        result,
        expected_status="checking",
        expected_phase="checking",
    )
    assert result["active_ticket_id"] == "p4-t2"

    event_types = _tx_event_types(repo_context)
    assert event_types == ["tx.begin", "tx.step.enter", "tx.user_intent.set"]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["phase"] == "checking"
    assert tx_state["active_tx"]["current_step"] == "p4-t2"


def test_ops_end_task_requires_commit_before_done(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=11,
        ticket_id="p5-t1",
        status="verified",
        phase="verified",
        current_step="p5-t1",
        next_action="tx.commit.start",
        semantic_summary="Ready to commit",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(
        ValueError,
        match="cannot mark task done before commit is finished",
    ):
        ops.ops_end_task(
            summary="Verified but not committed",
            status="done",
            task_id="p5-t1",
            session_id="s1",
        )


def test_ops_end_task_marks_done_after_commit(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=12,
        ticket_id="p5-t2",
        status="committed",
        phase="committed",
        current_step="p5-t2",
        next_action="tx.end.done",
        semantic_summary="Committed changes",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={
            "status": "passed",
            "last_result": {"sha": "abc123", "summary": "done"},
        },
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_end_task(
        summary="All work completed",
        next_action="tx.begin",
        status="done",
        task_id="p5-t2",
        session_id="s1",
    )

    _assert_workflow_guidance_fields(
        result,
        expected_status="done",
        expected_phase="done",
    )
    assert result["terminal"] is True
    assert result["followup_tool"] is None
    assert result["next_action"] == "tx.begin"
    assert _tx_event_types(repo_context)[-1] == "tx.end.done"


def test_ops_capture_state_persists_rebuilt_state(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(
        state_store, state_rebuilder, tx_id=21, ticket_id="p6-t1", session_id="s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    assert result["last_applied_seq"] >= 1
    assert result["integrity_status"] == "ok"
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["active_tx"]["ticket_id"] == "p6-t1"


def test_ops_task_summary_reflects_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=31,
        ticket_id="p7-t1",
        status="checking",
        phase="checking",
        current_step="p7-t1",
        next_action="tx.commit.start",
        semantic_summary="Compared acceptance criteria",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=400)

    assert result["ok"] is True
    assert result["summary"]["task_id"] == "p7-t1"
    assert result["summary"]["task_status"] == "checking"
    assert result["summary"]["next_step"] == "tx.commit.start"
    assert "task_summary:" in result["text"]
    assert "- task_status: checking" in result["text"]
    assert "- last_action: Compared acceptance criteria" in result["text"]


def test_ops_observability_summary_writes_json_and_text(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(
        state_store, state_rebuilder, tx_id=41, ticket_id="p8-t1", session_id="s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(
        session_id="s1",
        max_events=10,
        max_chars=300,
    )

    assert result["ok"] is True
    assert result["max_events"] == 10
    assert result["max_chars"] == 300
    assert repo_context.observability.exists()
    payload = json.loads(repo_context.observability.read_text(encoding="utf-8"))
    assert payload["session_id"] == "s1"
    assert isinstance(payload["recent_events"], list)
    assert payload["recent_events"]
    assert result["text"].startswith("observability_summary:")
