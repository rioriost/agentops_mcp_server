import json

import pytest

from agentops_mcp_server.ops_tools import (
    OpsTools,
    build_compact_context,
    summarize_result,
    truncate_text,
)


class DummyGitRepo:
    def diff_stat(self) -> str:
        return "diff"


def _build_ops_tools(repo_context, state_store, state_rebuilder):
    return OpsTools(repo_context, state_store, state_rebuilder, DummyGitRepo())


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


def _begin_tx(
    state_store, state_rebuilder, tx_id="t-1", session_id="s1", title="Build"
):
    state_store.repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    state_store.repo_context.tx_event_log.write_text("", encoding="utf-8")
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_event_append_and_state_save(
        tx_id=tx_id,
        ticket_id=tx_id,
        event_type="tx.begin",
        phase="in-progress",
        step_id="none",
        actor={"tool": "test"},
        session_id=session_id,
        payload={"ticket_id": tx_id, "ticket_title": title},
        state=rebuild["state"],
    )


def test_ops_compact_context_updates_journal(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_compact_context(max_chars=80, include_diff=False)

    assert result["ok"] is True
    assert isinstance(result["compact_context"], str)


def test_ops_handoff_export_writes_json(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["wrote"] is True
    assert result["path"]

    handoff_payload = json.loads(repo_context.handoff.read_text(encoding="utf-8"))
    assert "compact_context" in handoff_payload


def test_ops_start_task_bootstraps_tx_on_zero_event_baseline(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    event_types = [event["event_type"] for event in events]
    assert event_types == ["tx.begin", "tx.step.enter"]
    assert events[0]["payload"]["ticket_id"] == "t-1"
    assert events[0]["payload"]["ticket_title"] == "Build"
    assert events[1]["payload"]["step_id"] == "t-1"
    assert events[1]["payload"]["description"] == "task started"


def test_ops_start_task_requires_session_id(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_start_task(title="Build", task_id="t-1", session_id="")


def test_ops_start_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2"
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_records_step_after_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    event_types = [event["event_type"] for event in events]
    assert event_types == ["tx.begin", "tx.step.enter"]
    step_event = events[-1]
    assert step_event["tx_id"] == "t-1"
    assert step_event["session_id"] == "s1"
    assert step_event["payload"]["step_id"] == "t-1"
    assert step_event["payload"]["description"] == "task started"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


def test_ops_update_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_update_task(status="checking", note="step", session_id="s1")


def test_ops_update_task_requires_session_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_update_task(
            status="checking", note="step", task_id="t-1", session_id=""
        )


def test_ops_update_task_falls_back_to_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    ops.ops_update_task(status="blocked", note="waiting", session_id="s1")

    events = _read_tx_events(repo_context)
    update_events = [
        event
        for event in events
        if event["event_type"] == "tx.step.enter"
        and event.get("payload", {}).get("description") == "waiting"
    ]
    assert update_events
    assert update_events[-1]["tx_id"] == "t-1"
    assert update_events[-1]["session_id"] == "s1"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "blocked"
    assert active_tx["next_action"] == "tx.verify.start"


def test_ops_update_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_tx=t-2"
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-2",
            session_id="s1",
        )


def test_ops_update_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_tx=t-2. "
            "Resume active transaction 't-1' first \\(next_action=tx.verify.start\\)."
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-2",
            session_id="s1",
        )


def test_ops_resume_brief_reports_active_transaction_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="p1-t1", session_id="s1")
    ops.ops_update_task(
        status="checking",
        note="step",
        task_id="p1-t1",
        session_id="s1",
    )

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    brief = result["brief"]
    assert "- ticket_id: p1-t1" in brief
    assert "- status: checking" in brief
    assert "- next_action: tx.verify.start" in brief
    assert "- can_start_new_ticket: no" in brief
    assert (
        "- reason: active transaction exists and must be resumed before starting another ticket"
        in brief
    )


def test_ops_update_task_records_user_intent(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_update_task(
        status="checking",
        note="step",
        task_id="t-1",
        session_id="s1",
        user_intent="continue",
    )

    assert result["ok"] is True

    events = _read_tx_events(repo_context)
    tx_events = [event["event_type"] for event in events]
    assert tx_events == ["tx.begin", "tx.step.enter", "tx.user_intent.set"]
    assert events[-1]["payload"]["user_intent"] == "continue"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["user_intent"] == "continue"
    assert active_tx["semantic_summary"].startswith("Entered step")
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["next_action"] == "tx.verify.start"


def test_ops_end_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_end_task(summary="done", session_id="s1")


def test_ops_end_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_tx=t-2. "
            "Resume active transaction 't-1' first \\(next_action=tx.verify.start\\)."
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-2", session_id="s1")


def test_ops_end_task_requires_session_id(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_end_task(summary="done", task_id="t-1", session_id="")


def test_ops_end_task_emits_terminal_event_and_updates_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    result = ops.ops_end_task(
        summary="done",
        next_action="next",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    tx_events = _tx_event_types(repo_context)
    assert tx_events == ["tx.begin", "tx.step.enter", "tx.end.done"]

    events = _read_tx_events(repo_context)
    end_event = events[-1]
    assert end_event["session_id"] == "s1"
    assert end_event["payload"]["summary"] == "done"
    assert end_event["payload"]["next_action"] == "next"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    last_seq = max(event["seq"] for event in events)
    assert tx_state["last_applied_seq"] == last_seq
    assert tx_state["integrity"]["rebuilt_from_seq"] == last_seq


def test_ops_task_summary_emits_journal(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_id"] == "t-1"
    assert len(result["text"]) <= 40


def test_ops_observability_summary_includes_artifacts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    ops.ops_update_task(
        status="blocked",
        note="waiting",
        task_id="t-1",
        session_id="s1",
    )

    result = ops.ops_observability_summary(session_id="s1", max_events=5, max_chars=200)
    assert result["ok"] is True
    summary = result["summary"]
    assert summary["recent_events"]
    assert any(
        event.get("event_type") == "tx.begin" for event in summary["recent_events"]
    )

    assert repo_context.observability.exists()
    text_path = repo_context.observability.with_suffix(".txt")
    assert text_path.exists()


def test_ops_resume_brief_is_bounded(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_resume_brief(max_chars=20)
    assert result["ok"] is True
    assert len(result["brief"]) <= 20


def test_ops_capture_state_updates_tx_state(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_capture_state(session_id="s1")
    assert result["ok"] is True

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    events = _read_tx_events(repo_context)
    last_seq = max(event["seq"] for event in events)
    assert tx_state["last_applied_seq"] == last_seq


def test_ops_capture_state_returns_error_without_canonical_event_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["reason"] == "tx_event_log missing"


def test_ops_handoff_export_defaults_to_tx_begin_without_canonical_event_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["next_step"] == "tx.begin"


def test_truncate_text_variants():
    assert truncate_text(None) is None
    assert truncate_text("x", limit=0) == ""
    assert truncate_text("ok", limit=10) == "ok"
    assert truncate_text("x" * 10, limit=5).endswith("...(truncated)")


def test_build_compact_context_includes_diff():
    state = {"last_action": "done", "verification_status": "passed"}
    summary = build_compact_context(state, "diff", 200)
    assert "diff_stat" in summary
    assert "done" in summary


def test_summarize_result_truncates():
    result = summarize_result({"text": "x" * 3000}, limit=10)
    assert result["truncated"] is True


def test_ops_start_task_requires_title(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="title is required"):
        ops.ops_start_task(title="  ")


def test_ops_start_task_zero_event_baseline_requires_task_id_for_bootstrap(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_start_task(title="Build", session_id="s1")


def test_ops_update_task_requires_status_or_note(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="status or note is required"):
        ops.ops_update_task()


def test_ops_end_task_requires_summary(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="summary is required"):
        ops.ops_end_task(summary=" ")
