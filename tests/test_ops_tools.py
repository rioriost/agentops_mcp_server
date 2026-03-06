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
    return [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tx_event_types(repo_context):
    return [event["event_type"] for event in _read_tx_events(repo_context)]


def test_ops_compact_context_updates_snapshot_and_journal(
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


def test_ops_task_summary_emits_journal(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_id"] == "t-1"
    assert len(result["text"]) <= 40


def test_ops_observability_summary_includes_artifacts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

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

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_resume_brief(max_chars=20)
    assert result["ok"] is True
    assert len(result["brief"]) <= 20


def test_ops_task_lifecycle_records_events(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    start = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    update = ops.ops_update_task(status="blocked", note="waiting", session_id="s1")
    end = ops.ops_end_task(summary="done", next_action="next", session_id="s1")

    assert start["ok"] is True
    assert update["ok"] is True
    assert end["ok"] is True

    tx_events = _tx_event_types(repo_context)
    assert "tx.begin" in tx_events
    assert "tx.step.enter" in tx_events
    assert "tx.end.done" in tx_events


def test_ops_task_lifecycle_emits_tx_events_and_updates_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    ops.ops_update_task(
        status="checking",
        note="step",
        task_id="t-1",
        session_id="s1",
        user_intent="continue",
    )

    events = _read_tx_events(repo_context)
    tx_events = [event["event_type"] for event in events]
    assert "tx.begin" in tx_events
    assert "tx.step.enter" in tx_events
    assert "tx.user_intent.set" in tx_events
    assert (
        tx_events.index("tx.begin")
        < tx_events.index("tx.step.enter")
        < tx_events.index("tx.user_intent.set")
    )

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["user_intent"] == "continue"
    assert active_tx["semantic_summary"].startswith("Entered step")
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["next_action"] == "tx.verify.start"
    last_seq = max(event["seq"] for event in _read_tx_events(repo_context))
    assert tx_state["last_applied_seq"] == last_seq

    ops.ops_end_task(summary="done", next_action="next", status="done", task_id="t-1")
    tx_events = _tx_event_types(repo_context)
    assert "tx.end.done" in tx_events
    assert tx_events.index("tx.user_intent.set") < tx_events.index("tx.end.done")

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    last_seq = max(event["seq"] for event in _read_tx_events(repo_context))
    assert tx_state["last_applied_seq"] == last_seq
    assert tx_state["integrity"]["rebuilt_from_seq"] == last_seq


def test_ops_capture_state_updates_snapshot_and_checkpoint(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_capture_state(session_id="s1")
    assert result["ok"] is True

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    events = _read_tx_events(repo_context)
    last_seq = max(event["seq"] for event in events)
    assert tx_state["last_applied_seq"] == last_seq


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
