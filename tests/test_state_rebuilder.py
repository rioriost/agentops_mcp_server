import json
from datetime import datetime, timedelta, timezone

import pytest

from agentops_mcp_server.state_rebuilder import StateRebuilder


def _append_tx_event(state_store, **overrides):
    base = {
        "tx_id": 1,
        "ticket_id": "p4-t2",
        "event_type": "tx.begin",
        "phase": "in-progress",
        "step_id": "p4-t2-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
    }
    base.update(overrides)
    result = state_store.tx_event_append(**base)
    rebuilder = StateRebuilder(state_store.repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    if rebuild["ok"]:
        state_store.tx_state_save(rebuild["state"])
    return result


def _append_raw_tx_event(repo_context, event):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    with repo_context.tx_event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_rebuild_tx_state_requires_event_log(repo_context, state_rebuilder):
    result = state_rebuilder.rebuild_tx_state()
    assert result["ok"] is False
    assert result["reason"] == "tx_event_log missing"


def test_rebuild_tx_state_accepts_empty_event_log(repo_context, state_rebuilder):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = state_rebuilder.rebuild_tx_state()

    assert result["ok"] is True
    assert result["source"] == "rebuild"
    assert result["last_applied_seq"] == 0
    assert result["rebuilt_from_seq"] == 0
    assert result["invalid_lines"] == 0
    assert result["dropped_events"] == 0
    assert result["event_log_path"] == str(repo_context.tx_event_log)

    state = result["state"]
    assert state["schema_version"] == "0.4.0"
    assert state["last_applied_seq"] == 0
    assert state["integrity"]["rebuilt_from_seq"] == 0
    assert isinstance(state["integrity"]["state_hash"], str)
    assert state["integrity"]["state_hash"]
    assert state["updated_at"]

    assert state["active_tx"] is None
    assert state["status"] is None
    assert state["next_action"] == "tx.begin"
    assert state["semantic_summary"] is None
    assert state["verify_state"] is None
    assert state["commit_state"] is None


def test_rebuild_tx_state_empty_event_log_ignores_sparse_seeded_tx_state(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(
        json.dumps(
            {
                "schema_version": "0.4.0",
                "updated_at": "2026-03-08T00:00:00Z",
                "active_tx": {
                    "tx_id": "",
                    "ticket_id": "",
                    "status": "planned",
                    "phase": "planned",
                    "current_step": "none",
                    "last_completed_step": "",
                    "next_action": "",
                    "semantic_summary": "Initialized transaction state",
                    "user_intent": None,
                    "verify_state": {"status": "not_started", "last_result": None},
                    "commit_state": {"status": "not_started", "last_result": None},
                    "file_intents": [],
                },
                "last_applied_seq": 0,
                "integrity": {"state_hash": "", "rebuilt_from_seq": 0},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rebuild_tx_state()

    assert result["ok"] is True
    assert result["last_applied_seq"] == 0
    state = result["state"]
    assert state["active_tx"] is None
    assert state["status"] is None
    assert state["next_action"] == "tx.begin"
    assert state["semantic_summary"] is None


def test_read_tx_event_log_filters_seq(repo_context, state_store, state_rebuilder):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )

    events = state_rebuilder.read_tx_event_log(start_seq=1)
    assert [event["seq"] for event in events["events"]] == [2]

    events = state_rebuilder.read_tx_event_log(start_seq=0, end_seq=1)
    assert [event["seq"] for event in events["events"]] == [1]


def test_read_tx_event_log_handles_invalid_lines(repo_context, state_rebuilder):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps(["not", "a", "dict"]),
                json.dumps({"seq": "nope"}),
                json.dumps({"seq": 1, "tx_id": "t", "ticket_id": "x"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.read_tx_event_log(start_seq=0)
    assert result["invalid_lines"] == 3
    assert [event["seq"] for event in result["events"]] == [1]


def test_read_recent_tx_events_returns_tail(repo_context, state_store, state_rebuilder):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s3",
        payload={"step_id": "p4-t2-s3", "description": "step"},
    )

    events = state_rebuilder.read_recent_tx_events(2)
    assert [event["seq"] for event in events] == [2, 3]


def test_rebuild_tx_state_uses_materialized_when_intact(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_state_save(rebuild["state"])

    rebuild_again = state_rebuilder.rebuild_tx_state()
    assert rebuild_again["ok"] is True
    assert rebuild_again["source"] == "materialized"
    assert rebuild_again["rebuilt_from_seq"] == rebuild_again["last_applied_seq"]
    assert rebuild_again["state"]["integrity"]["drift_detected"] is False
    assert rebuild_again["state"]["integrity"]["active_tx_source"] == "materialized"


def test_rebuild_tx_state_reconstructs_in_progress_next_action_from_canonical_fields(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s1",
        payload={"step_id": "p4-t2-s1", "description": "step"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.add",
        payload={
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t2-s1",
            "state": "planned",
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state = rebuild["state"]
    assert state["status"] == "in-progress"
    assert state["next_action"] == "tx.verify.start"


def test_rebuild_tx_state_keeps_active_tx_minimal_identity_subset(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s1",
        payload={"step_id": "p4-t2-s1", "description": "task started"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t2"
    assert set(active_tx.keys()) <= {"tx_id", "ticket_id", "_last_event_seq"}


def test_rebuild_tx_state_committed_next_action(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.verify.start",
        phase="checking",
        payload={"command": "verify"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.verify.pass",
        phase="verified",
        payload={"ok": True, "returncode": 0, "summary": "ok"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.commit.start",
        phase="verified",
        payload={
            "message": "commit",
            "files": "auto",
            "branch": "main",
            "diff_summary": "diff",
        },
    )
    _append_tx_event(
        state_store,
        event_type="tx.commit.done",
        phase="committed",
        payload={
            "sha": "abc123",
            "summary": "done",
            "branch": "main",
            "diff_summary": "diff",
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert rebuild["state"]["status"] == "committed"
    assert rebuild["state"]["next_action"] == "tx.end.done"


def test_rebuild_tx_state_torn_event_truncates(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(repo_context, {"seq": 2, "event_id": "evt-bad", "tx_id": 1})

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_missing_file_intent_truncates(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-missing-intent",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.file_intent.update",
            "phase": "in-progress",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"path": "missing.py", "state": "started"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "file intent missing for path"
    assert rebuild["state"]["rebuild_invalid_seq"] == 2
    assert (
        rebuild["state"]["rebuild_invalid_event"]["event_type"]
        == "tx.file_intent.update"
    )
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"


def test_rebuild_tx_state_recovers_latest_active_tx_after_stale_terminal_begin(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(
        state_store,
        tx_id=101,
        ticket_id="p4-t2",
        step_id="none",
        payload={"ticket_id": "p4-t2", "ticket_title": "old"},
    )
    _append_tx_event(
        state_store,
        tx_id=101,
        ticket_id="p4-t2",
        event_type="tx.end.done",
        phase="done",
        step_id="p4-t2-s1",
        payload={"summary": "done"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "evt-stale-rebegin",
            "tx_id": 101,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "old restart"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 4,
            "event_id": "evt-new-begin",
            "tx_id": 102,
            "ticket_id": "p2-t3",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p2-t3", "ticket_title": "new tx"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 5,
            "event_id": "evt-new-step",
            "tx_id": 102,
            "ticket_id": "p2-t3",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p2-t3",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p2-t3", "description": "task started"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 5
    assert "rebuild_warning" not in rebuild["state"]
    assert "rebuild_invalid_seq" not in rebuild["state"]
    assert rebuild["state"]["active_tx"]["tx_id"] == 102
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p2-t3"
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert rebuild["state"]["integrity"]["active_tx_source"] == "active_candidate"


def test_rebuild_tx_state_prefers_latest_non_terminal_tx_across_sessions(
    repo_context, state_store, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "evt-s1-begin",
            "tx_id": 201,
            "ticket_id": "p1-t1",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p1-t1", "ticket_title": "old tx"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-s1-end",
            "tx_id": 201,
            "ticket_id": "p1-t1",
            "event_type": "tx.end.done",
            "phase": "done",
            "step_id": "p1-t1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"summary": "done"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "evt-s2-begin",
            "tx_id": 202,
            "ticket_id": "p2-t3",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a2"},
            "session_id": "s2",
            "payload": {"ticket_id": "p2-t3", "ticket_title": "active tx"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 4,
            "event_id": "evt-s2-step",
            "tx_id": 202,
            "ticket_id": "p2-t3",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p2-t3",
            "actor": {"agent_id": "a2"},
            "session_id": "s2",
            "payload": {"step_id": "p2-t3", "description": "task started"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 4
    assert rebuild["state"]["active_tx"]["tx_id"] == 202
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p2-t3"
    assert set(rebuild["state"]["active_tx"].keys()) <= {
        "tx_id",
        "ticket_id",
        "_last_event_seq",
    }
    assert rebuild["state"]["status"] == "in-progress"
    assert rebuild["state"]["next_action"] == "tx.verify.start"
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert rebuild["state"]["integrity"]["active_tx_source"] == "active_candidate"


def test_rebuild_tx_state_uses_materialized_none_state_without_false_drift(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t3",
        step_id="none",
        payload={"ticket_id": "p2-t3", "ticket_title": "tx"},
    )
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t3",
        event_type="tx.end.done",
        phase="done",
        step_id="p2-t3",
        payload={"summary": "done"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_state_save(rebuild["state"])

    rebuild_again = state_rebuilder.rebuild_tx_state()

    assert rebuild_again["ok"] is True
    assert rebuild_again["source"] == "materialized"
    assert rebuild_again["last_applied_seq"] == 2
    assert rebuild_again["rebuilt_from_seq"] == 2
    assert rebuild_again["state"]["active_tx"] is None
    assert rebuild_again["state"]["status"] is None
    assert rebuild_again["state"]["next_action"] == "tx.begin"
    assert rebuild_again["state"]["integrity"]["drift_detected"] is False
    assert rebuild_again["state"]["integrity"]["active_tx_source"] == "none"
    assert "rebuild_warning" not in rebuild_again["state"]


def test_rebuild_tx_state_marks_drift_when_applied_seq_has_no_active_tx(
    repo_context, state_store, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "e1",
            "ts": "2026-03-08T00:00:00+00:00",
            "project_root": str(repo_context.get_repo_root()),
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "e2",
            "ts": "2026-03-08T00:00:01+00:00",
            "project_root": str(repo_context.get_repo_root()),
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.end.done",
            "phase": "done",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"summary": "done"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 2
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert rebuild["state"]["integrity"]["active_tx_source"] == "none"
    assert "rebuild_warning" not in rebuild["state"]
    assert "rebuild_invalid_seq" not in rebuild["state"]
    assert "rebuild_observed_mismatch" not in rebuild["state"]


def test_rebuild_tx_state_logs_observed_mismatch_for_invalid_ordering(
    repo_context, state_store, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "e1",
            "ts": "2026-03-08T00:00:00+00:00",
            "project_root": str(repo_context.get_repo_root()),
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "e2",
            "ts": "2026-03-08T00:00:01+00:00",
            "project_root": str(repo_context.get_repo_root()),
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.commit.start",
            "phase": "verified",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {
                "message": "commit without verify pass",
                "files": "auto",
                "branch": "main",
                "diff_summary": "diff",
            },
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["integrity"]["drift_detected"] is True
    assert rebuild["state"]["rebuild_warning"] == "commit.start requires verify.pass"
    assert rebuild["state"]["rebuild_invalid_seq"] == 2

    observed = rebuild["state"]["rebuild_observed_mismatch"]
    assert observed["drift_reason"] == "commit.start requires verify.pass"
    assert observed["last_applied_seq"] == 1
    assert observed["active_tx_id"] == 0
    assert observed["active_ticket_id"] == "none"
    assert observed["invalid_reason"] == "commit.start requires verify.pass"
    assert observed["invalid_event"]["seq"] == 2
    assert observed["invalid_event"]["event_type"] == "tx.commit.start"
    assert observed["event_log_path"] == str(repo_context.tx_event_log)

    error_lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(error_lines) == 1
    assert error_lines[0]["tool_name"] == "rebuild_tx_state"
    assert error_lines[0]["tool_output"]["error"] == "commit.start requires verify.pass"
    assert (
        error_lines[0]["tool_output"]["observed_mismatch"]["invalid_event"][
            "event_type"
        ]
        == "tx.commit.start"
    )
    assert error_lines[0]["tool_output"]["observed_mismatch"]["last_applied_seq"] == 1
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"


def test_rebuild_tx_state_logs_observed_mismatch_for_duplicate_begin(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-duplicate-begin",
            "tx_id": 1,
            "ticket_id": "p2-t3",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p2-t3", "ticket_title": "duplicate begin"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["integrity"]["drift_detected"] is True
    assert rebuild["state"]["rebuild_warning"] == "duplicate tx.begin"
    assert rebuild["state"]["rebuild_invalid_seq"] == 2
    assert rebuild["state"]["rebuild_invalid_event"]["seq"] == 2
    assert rebuild["state"]["rebuild_invalid_event"]["event_type"] == "tx.begin"
    assert rebuild["state"]["rebuild_invalid_event"]["tx_id"] == 1
    assert rebuild["state"]["rebuild_invalid_event"]["ticket_id"] == "p2-t3"
    assert rebuild["state"]["rebuild_invalid_event"]["session_id"] == "s1"
    assert (
        rebuild["state"]["rebuild_invalid_event"]["payload"]["ticket_title"]
        == "duplicate begin"
    )

    observed = rebuild["state"]["rebuild_observed_mismatch"]
    assert observed["drift_reason"] == "duplicate tx.begin"
    assert observed["last_applied_seq"] == 1
    assert observed["active_tx_id"] == 0
    assert observed["active_ticket_id"] == "none"
    assert observed["invalid_reason"] == "duplicate tx.begin"
    assert observed["invalid_event"]["seq"] == 2
    assert observed["invalid_event"]["event_type"] == "tx.begin"
    assert observed["invalid_event"]["tx_id"] == 1
    assert observed["event_log_path"] == str(repo_context.tx_event_log)

    error_lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(error_lines) == 1
    assert error_lines[0]["tool_name"] == "rebuild_tx_state"
    assert error_lines[0]["tool_output"]["error"] == "duplicate tx.begin"
    assert (
        error_lines[0]["tool_output"]["observed_mismatch"]["invalid_event"][
            "event_type"
        ]
        == "tx.begin"
    )
    assert (
        error_lines[0]["tool_output"]["observed_mismatch"]["invalid_event"]["seq"] == 2
    )
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"


def test_rebuild_tx_state_duplicate_begin_reports_invalid_seq_not_last_valid_seq(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t01",
        step_id="none",
        payload={"ticket_id": "p2-t01", "ticket_title": "first release"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-duplicate-begin",
            "tx_id": 1,
            "ticket_id": "p2-t01",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p2-t01", "ticket_title": "duplicate begin"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "duplicate tx.begin"
    assert rebuild["state"]["rebuild_invalid_seq"] == 2
    assert rebuild["state"]["rebuild_invalid_seq"] != rebuild["last_applied_seq"]

    observed = rebuild["state"]["rebuild_observed_mismatch"]
    assert observed["last_applied_seq"] == 1
    assert observed["invalid_reason"] == "duplicate tx.begin"
    assert observed["invalid_event"]["seq"] == 2
    assert rebuild["state"]["rebuild_invalid_seq"] == observed["invalid_event"]["seq"]


def test_rebuild_tx_state_detects_ticket_label_collision_across_distinct_tx_ids(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(
        state_store,
        tx_id=301,
        ticket_id="p2-t01",
        step_id="none",
        payload={"ticket_id": "p2-t01", "ticket_title": "release 1"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-collision-begin",
            "tx_id": 302,
            "ticket_id": "p2-t01",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a2"},
            "session_id": "s2",
            "payload": {"ticket_id": "p2-t01", "ticket_title": "release 2"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 2
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert "rebuild_warning" not in rebuild["state"]
    assert "rebuild_invalid_seq" not in rebuild["state"]
    assert "rebuild_invalid_event" not in rebuild["state"]

    assert rebuild["state"]["active_tx"]["tx_id"] == 302
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p2-t01"
    assert rebuild["state"]["integrity"]["active_tx_source"] == "active_candidate"


def test_rebuild_tx_state_allows_tx_begin_after_terminal_for_same_tx(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t3",
        step_id="none",
        payload={"ticket_id": "p2-t3", "ticket_title": "first run"},
    )
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t3",
        event_type="tx.step.enter",
        phase="in-progress",
        step_id="p2-t3",
        payload={"step_id": "p2-t3", "description": "task started"},
    )
    _append_tx_event(
        state_store,
        tx_id=1,
        ticket_id="p2-t3",
        event_type="tx.end.done",
        phase="done",
        step_id="p2-t3",
        payload={"summary": "done"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 4,
            "event_id": "evt-rebegin",
            "tx_id": 1,
            "ticket_id": "p2-t3",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p2-t3", "ticket_title": "second run"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 5,
            "event_id": "evt-second-step",
            "tx_id": 1,
            "ticket_id": "p2-t3",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p2-t3-second",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {
                "step_id": "p2-t3-second",
                "description": "task restarted",
            },
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 5
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert rebuild["state"]["integrity"]["active_tx_source"] == "none"
    assert "rebuild_warning" not in rebuild["state"]
    assert "rebuild_invalid_seq" not in rebuild["state"]
    assert "rebuild_observed_mismatch" not in rebuild["state"]


def test_rebuild_tx_state_preserves_user_intent(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.user_intent.set",
        payload={"user_intent": "continue"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t2"
    assert set(active_tx.keys()) <= {"tx_id", "ticket_id", "_last_event_seq"}
    assert rebuild["state"]["status"] == "in-progress"
    assert rebuild["state"]["next_action"] == "tx.verify.start"


def test_rebuild_tx_state_semantic_summary_fallback(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t2"
    assert set(active_tx.keys()) <= {"tx_id", "ticket_id", "_last_event_seq"}
    assert isinstance(rebuild["state"]["semantic_summary"], str)
    assert rebuild["state"]["semantic_summary"]


def test_rebuild_tx_state_user_intent_guides_resume(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.user_intent.set",
        payload={"user_intent": "continue"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t2"
    assert set(active_tx.keys()) <= {"tx_id", "ticket_id", "_last_event_seq"}
    assert rebuild["state"]["status"] == "in-progress"
    assert rebuild["state"]["next_action"] == "tx.verify.start"


def test_rebuild_tx_state_rejects_verified_intent_before_verify_pass(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s1",
        payload={"step_id": "p4-t2-s1", "description": "step"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.add",
        payload={
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t2-s1",
            "state": "planned",
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 4,
            "event_id": "evt-verified-before-pass",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.file_intent.update",
            "phase": "in-progress",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"path": "a.py", "state": "verified"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 3


def test_rebuild_tx_state_drops_duplicate_event_ids_without_drift(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "evt-begin",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-step",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p4-t2-s1", "description": "step"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "evt-step",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s1-dup",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p4-t2-s1-dup", "description": "duplicate"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 2
    assert rebuild["dropped_events"] == 1
    assert rebuild["state"]["active_tx"]["tx_id"] == 1
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p4-t2"
    assert set(rebuild["state"]["active_tx"].keys()) <= {
        "tx_id",
        "ticket_id",
        "_last_event_seq",
    }
    assert rebuild["state"]["integrity"]["drift_detected"] is False
    assert "rebuild_warning" not in rebuild["state"]


def test_rebuild_tx_state_marks_drift_when_latest_event_is_terminal_for_other_tx(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "evt-active-begin",
            "tx_id": 401,
            "ticket_id": "p2-t3",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p2-t3", "ticket_title": "active tx"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-active-step",
            "tx_id": 401,
            "ticket_id": "p2-t3",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p2-t3-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p2-t3-s1", "description": "active step"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "evt-done-begin",
            "tx_id": 402,
            "ticket_id": "p4-t5",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a2"},
            "session_id": "s2",
            "payload": {"ticket_id": "p4-t5", "ticket_title": "done tx"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 4,
            "event_id": "evt-done-end",
            "tx_id": 402,
            "ticket_id": "p4-t5",
            "event_type": "tx.end.done",
            "phase": "done",
            "step_id": "p4-t5-s1",
            "actor": {"agent_id": "a2"},
            "session_id": "s2",
            "payload": {"summary": "done"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 4
    assert rebuild["state"]["active_tx"]["tx_id"] == 401
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p2-t3"
    assert rebuild["state"]["integrity"]["drift_detected"] is True
    assert (
        rebuild["state"]["rebuild_warning"]
        == "selected active transaction does not match the latest canonical event sequence"
    )
    observed = rebuild["state"]["rebuild_observed_mismatch"]
    assert observed["active_tx_id"] == 401
    assert observed["active_ticket_id"] == "p2-t3"
    assert observed["last_applied_seq"] == 4


def test_validate_tx_event_invariants_resets_context_after_terminal_rebegin(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {"path": "a.py", "planned_step": "s1", "state": "planned"},
        },
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.end.done", "step_id": "s1", "payload": {"summary": "done"}},
    )
    assert valid is True
    assert context["terminal"] is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.begin",
            "tx_id": 1,
            "step_id": "none",
            "payload": {"ticket_id": "t"},
        },
    )
    assert valid is True
    assert context["terminal"] is False
    assert context["steps"] == set()
    assert context["intent_states"] == {}
    assert context["intent_steps"] == {}
    assert context["verify_started_steps"] == set()
    assert context["verify_passed"] is False
    assert context["commit_started"] is False


def test_rebuild_tx_state_truncates_on_missing_commit_fail_error(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-commit-fail-missing-error",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.commit.fail",
            "phase": "verified",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "missing payload.error"
    assert rebuild["state"]["rebuild_invalid_event"]["event_type"] == "tx.commit.fail"
    assert rebuild["state"]["integrity"]["drift_detected"] is True


def test_rebuild_tx_state_truncates_on_missing_user_intent_payload(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-user-intent-missing",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.user_intent.set",
            "phase": "in-progress",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "missing payload.user_intent"
    assert (
        rebuild["state"]["rebuild_invalid_event"]["event_type"] == "tx.user_intent.set"
    )
    assert rebuild["state"]["integrity"]["drift_detected"] is True


def test_rebuild_tx_state_truncates_on_missing_end_blocked_reason(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-end-blocked-missing-reason",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.end.blocked",
            "phase": "blocked",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "missing payload.reason"
    assert rebuild["state"]["rebuild_invalid_event"]["event_type"] == "tx.end.blocked"
    assert rebuild["state"]["integrity"]["drift_detected"] is True


def test_rebuild_tx_state_preserves_empty_session_metadata_without_recording_last_session(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "evt-empty-session-begin",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-empty-session-dup-begin",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "duplicate"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    observed = rebuild["state"]["rebuild_observed_mismatch"]
    assert rebuild["state"]["rebuild_warning"] == "duplicate tx.begin"
    assert observed["invalid_reason"] == "duplicate tx.begin"
    assert observed["last_session_by_tx"] == {}


def test_rebuild_tx_state_falls_back_semantic_summary_for_selected_active_tx(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 1,
            "event_id": "evt-begin-no-summary",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["active_tx"]["tx_id"] == 1
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p4-t2"
    assert set(rebuild["state"]["active_tx"].keys()) <= {
        "tx_id",
        "ticket_id",
        "_last_event_seq",
    }
    assert rebuild["state"]["semantic_summary"] == "Started transaction p4-t2"

    rebuild["state"]["semantic_summary"] = ""
    rebuild["state"]["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(
        rebuild["state"]
    )

    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(
        json.dumps(rebuild["state"], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    rebuild_again = state_rebuilder.rebuild_tx_state()

    assert rebuild_again["ok"] is True
    assert rebuild_again["state"]["active_tx"]["tx_id"] == 1
    assert rebuild_again["state"]["active_tx"]["ticket_id"] == "p4-t2"
    assert set(rebuild_again["state"]["active_tx"].keys()) <= {
        "tx_id",
        "ticket_id",
        "_last_event_seq",
    }
    assert rebuild_again["state"]["semantic_summary"] == "Started transaction p4-t2"


def test_rebuild_tx_state_preserves_invalid_event_seq_in_rebuild_invalid_seq(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-dup-begin-last-valid",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "none",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "duplicate"},
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_invalid_event"]["seq"] == 2
    assert rebuild["state"]["rebuild_invalid_seq"] == 2
    assert rebuild["state"]["rebuild_warning"] == "duplicate tx.begin"


def test_rebuild_tx_state_reports_drift_for_stale_materialized_active_tx(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s1",
        payload={"step_id": "p4-t2-s1", "description": "step"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True

    stale_state = json.loads(json.dumps(rebuild["state"], ensure_ascii=False))
    stale_state["active_tx"]["_last_event_seq"] = 1
    stale_state["active_tx"]["semantic_summary"] = ""
    stale_state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(
        stale_state
    )

    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(
        json.dumps(stale_state, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    rebuild_again = state_rebuilder.rebuild_tx_state()

    assert rebuild_again["ok"] is True
    assert rebuild_again["source"] == "rebuild"
    assert rebuild_again["state"]["active_tx"]["tx_id"] == 1
    assert rebuild_again["state"]["active_tx"]["ticket_id"] == "p4-t2"
    assert set(rebuild_again["state"]["active_tx"].keys()) <= {
        "tx_id",
        "ticket_id",
        "_last_event_seq",
    }


def test_truncate_and_resolve_path(state_rebuilder, repo_context, tmp_path):
    assert state_rebuilder._truncate_text(None) is None
    assert state_rebuilder._truncate_text("x", limit=0) == ""
    assert state_rebuilder._truncate_text("ok", limit=10) == "ok"
    assert state_rebuilder._truncate_text("x" * 10, limit=5).endswith("...(truncated)")

    resolved = state_rebuilder.resolve_path(
        "logs/events.jsonl", repo_context.tx_event_log
    )
    assert resolved == repo_context.get_repo_root() / "logs/events.jsonl"

    abs_path = tmp_path / "abs.jsonl"
    assert (
        state_rebuilder.resolve_path(str(abs_path), repo_context.tx_event_log)
        == abs_path
    )


def test_state_hash_ignores_updated_at_and_internal_fields(state_rebuilder):
    state = state_rebuilder._init_tx_state()
    state["active_tx"] = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    state["active_tx"]["phase"] = "in-progress"
    state["active_tx"]["current_step"] = "s1"
    state["active_tx"]["next_action"] = "next"
    state["active_tx"]["semantic_summary"] = "summary"
    state["last_applied_seq"] = 1
    state["integrity"]["rebuilt_from_seq"] = 1
    state["integrity"]["state_hash"] = ""

    hash1 = state_rebuilder._compute_state_hash(state)
    state["updated_at"] = "2000-01-01T00:00:00+00:00"
    state["active_tx"]["_last_event_seq"] = 99
    state["active_tx"]["_terminal"] = True
    hash2 = state_rebuilder._compute_state_hash(state)
    assert hash1 == hash2

    state["active_tx"]["semantic_summary"] = "changed"
    assert state_rebuilder._compute_state_hash(state) != hash1


def test_parse_iso_ts_and_read_first_event_with_ts(state_rebuilder, repo_context):
    assert state_rebuilder.parse_iso_ts("not-a-ts") is None
    assert state_rebuilder.parse_iso_ts("2024-01-01T00:00:00Z") is not None

    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"ts": "bad"}),
                json.dumps({"ts": "2024-01-01T00:00:00Z"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    first = state_rebuilder.read_first_event_with_ts(journal)
    assert first is not None
    rec, parsed = first
    assert rec["ts"].endswith("Z")
    assert parsed.tzinfo is not None


def test_rotate_journal_if_prev_week(state_rebuilder, repo_context):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    current_week = state_rebuilder.week_start_utc(now)
    last_week_start = current_week - timedelta(days=7)

    last_week_ts = (last_week_start + timedelta(hours=1)).isoformat()
    current_week_ts = (current_week + timedelta(hours=1)).isoformat()

    journal.write_text(
        "\n".join(
            [
                json.dumps({"ts": last_week_ts, "event": "old"}),
                json.dumps({"ts": current_week_ts, "event": "new"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is True
    assert result["rotated"] is True
    assert "archive" in result
    assert "archived" in result
    assert "kept" in result


def test_rotate_journal_missing_returns_reason(state_rebuilder, repo_context):
    journal = repo_context.journal
    if journal.exists():
        journal.unlink()
    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is False
    assert result["reason"] == "journal not found"


def test_init_replay_state_defaults(state_rebuilder):
    state = state_rebuilder.init_replay_state(
        {
            "task_id": 123,
            "plan_steps": "nope",
            "replay_warnings": {"invalid_lines": "x"},
        }
    )
    assert state["task_id"] == ""
    assert state["plan_steps"] == []
    assert state["replay_warnings"]["invalid_lines"] == "x"
    assert state["replay_warnings"]["dropped_events"] == 0


def test_select_target_session_id(state_rebuilder):
    events = [
        {"seq": 1, "session_id": "s1", "kind": "session.start"},
        {"seq": 2, "session_id": "s2"},
        {"seq": 3, "session_id": "s3", "kind": "session.start"},
    ]
    assert state_rebuilder.select_target_session_id(events, None) == "s3"
    assert state_rebuilder.select_target_session_id(events, "preferred") == "preferred"


def test_append_applied_event_id_trims(state_rebuilder):
    state = {"applied_event_ids": ["e1", "e2", "e3"]}
    state_rebuilder.append_applied_event_id(state, "e4", max_size=3)
    assert state["applied_event_ids"] == ["e2", "e3", "e4"]


def test_apply_event_to_state_covers_branches(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)

    state_rebuilder.apply_event_to_state(
        state, {"kind": "session.start", "session_id": "s1", "payload": {}}
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "session.end", "session_id": "s1", "payload": {}}
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.start",
            "session_id": "s1",
            "payload": {"title": "Build", "task_id": "t-1"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.update",
            "session_id": "s1",
            "payload": {"status": "checking", "note": "step"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.end",
            "session_id": "s1",
            "payload": {"summary": "done", "next_action": "next"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.created",
            "session_id": "s1",
            "payload": {"task_id": "t-2", "title": "Plan", "status": "planned"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.progress",
            "session_id": "s1",
            "payload": {"status": "in-progress", "note": ""},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "task.blocked",
            "session_id": "s1",
            "payload": {"reason": "waiting", "note": "blocked"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "plan.start", "session_id": "s1", "payload": {"steps": []}}
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "plan.step", "session_id": "s1", "payload": {"step": "s1"}}
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "plan.end", "session_id": "s1", "payload": {}}
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "artifact.summary",
            "session_id": "s1",
            "payload": {"summary": "ok"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "verify.start", "session_id": "s1", "payload": {}}
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.end",
            "session_id": "s1",
            "payload": {
                "ok": False,
                "returncode": 1,
                "stdout": "x" * 600,
                "stderr": "fail",
            },
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.result",
            "session_id": "s1",
            "payload": {
                "ok": False,
                "returncode": 2,
                "stderr": "nope",
                "reason": "bad",
            },
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {"kind": "commit.start", "session_id": "s1", "payload": {"message": "m"}},
    )
    state_rebuilder.apply_event_to_state(
        state,
        {"kind": "commit.end", "session_id": "s1", "payload": {"sha": "abc"}},
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "file.edit",
            "session_id": "s1",
            "payload": {"action": "edit", "path": "a.py"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "tool.result",
            "session_id": "s1",
            "payload": {"ok": False, "error": "bad"},
        },
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "error", "session_id": "s1", "payload": {"message": "boom"}}
    )

    assert state["session_id"] == "s1"
    assert state["task_id"] == "t-2"
    assert state["last_action"]


def test_replay_events_to_state_filters_and_drops(state_rebuilder):
    events = [
        {"seq": 1, "kind": "session.start", "session_id": "s1", "payload": {}},
        {
            "seq": 2,
            "kind": "task.start",
            "session_id": "s1",
            "event_id": "e1",
            "payload": {"title": "Build", "task_id": "t-1"},
        },
        {"seq": 3, "kind": "session.start", "session_id": "s2", "payload": {}},
        {
            "seq": 4,
            "kind": "task.start",
            "session_id": "s2",
            "event_id": "e2",
            "payload": {"title": "Deploy", "task_id": "t-2"},
        },
        {
            "seq": 5,
            "kind": "task.update",
            "session_id": "s2",
            "event_id": "e2",
            "payload": {"status": "checking", "note": "dup"},
        },
    ]
    state = state_rebuilder.replay_events_to_state(
        None, events, preferred_session_id=None, invalid_lines=2
    )
    assert state["session_id"] == "s2"
    assert state["task_id"] == "t-2"
    assert state["replay_warnings"]["invalid_lines"] == 2
    assert state["replay_warnings"]["dropped_events"] == 1


def test_derive_next_action_and_integrity(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status=None,
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary=None,
        )
        == "tx.begin"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="checking",
            verify_state={"status": "failed"},
            commit_state={"status": "not_started"},
            active_tx=None,
            semantic_summary="",
        )
        == "fix and re-verify"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="verified",
            verify_state={"status": "passed"},
            commit_state={"status": "not_started"},
            active_tx=None,
            semantic_summary="",
        )
        == "tx.commit.start"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="verified",
            verify_state={"status": "passed"},
            commit_state={"status": "done"},
            active_tx=None,
            semantic_summary="",
        )
        == "tx.end.done"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="committed",
            verify_state=None,
            commit_state={"status": "done"},
            active_tx=None,
            semantic_summary="",
        )
        == "tx.end.done"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="blocked",
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary="",
        )
        == "tx.end.blocked"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="done",
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary="",
        )
        == "tx.end.done"
    )

    state = state_rebuilder._init_tx_state()
    state["active_tx"] = {
        "tx_id": 1,
        "ticket_id": "t-1",
        "phase": "in-progress",
        "_last_event_seq": 1,
    }
    state["status"] = "in-progress"
    state["next_action"] = "tx.verify.start"
    state["semantic_summary"] = "summary"
    state["last_applied_seq"] = 1
    state["integrity"]["rebuilt_from_seq"] = 1
    state["integrity"]["active_tx_source"] = "active_candidate"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 1) is True
    state["last_applied_seq"] = 2
    assert state_rebuilder._tx_state_integrity_ok(state, 1) is False


def test_read_tx_event_log_invalid_ranges(state_rebuilder):
    with pytest.raises(ValueError, match="start_seq must be >= 0"):
        state_rebuilder.read_tx_event_log(start_seq=-1)
    with pytest.raises(ValueError, match="end_seq must be >= start_seq"):
        state_rebuilder.read_tx_event_log(start_seq=2, end_seq=1)


def test_read_recent_tx_events_empty(state_rebuilder, repo_context):
    assert state_rebuilder.read_recent_tx_events(0) == []
    if repo_context.tx_event_log.exists():
        repo_context.tx_event_log.unlink()
    assert state_rebuilder.read_recent_tx_events(3) == []


def test_validate_tx_event_missing_fields(state_rebuilder):
    valid, _ = state_rebuilder._validate_tx_event({"seq": 1})
    assert valid is False


def test_validate_tx_event_payload_variants(state_rebuilder):
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.begin", {"ticket_id": "t-1"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload("tx.begin", {}, "s1")
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.step.enter", {"step_id": "s1"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.step.enter", {"step_id": "s2"}, "s1"
    )
    assert ok is True

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "tests",
            "planned_step": "s1",
            "state": "planned",
        },
        "s1",
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "a.py",
            "operation": "bogus",
            "purpose": "tests",
            "planned_step": "s1",
        },
        "s1",
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.update", {"path": "a.py", "state": "started"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.update", {"path": "a.py", "state": "bad"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.complete", {"path": "a.py", "state": "verified"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.complete", {"path": "a.py", "state": "started"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.start",
        {"message": "m", "branch": "main", "diff_summary": "diff"},
        "s1",
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload("tx.commit.start", {}, "s1")
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.done", {"sha": "abc", "branch": "main", "diff_summary": "diff"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload("tx.commit.done", {}, "s1")
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.end.done", {"summary": "done"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload("tx.end.done", {}, "s1")
    assert ok is False


def test_validate_tx_event_invariants_branches(state_rebuilder):
    context = state_rebuilder._init_tx_context()

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {
                "path": "a.py",
                "planned_step": "s1",
                "state": "planned",
            },
        },
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {
                "path": "a.py",
                "planned_step": "s1",
                "state": "planned",
            },
        },
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.verify.start", "step_id": "s1", "payload": {}},
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.verify.pass", "step_id": "s1", "payload": {"ok": True}},
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.commit.start", "step_id": "s1", "payload": {}},
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.commit.done", "step_id": "s1", "payload": {}},
    )
    assert valid is False


def test_update_semantic_summary_variants(state_rebuilder):
    assert state_rebuilder._update_semantic_summary(
        "tx.file_intent.add", {"path": "a.py", "operation": "update"}, "s1"
    ).startswith("Planned")
    assert state_rebuilder._update_semantic_summary(
        "tx.file_intent.update", {"path": "a.py", "state": "started"}, "s1"
    ).startswith("Updated intent")
    assert state_rebuilder._update_semantic_summary(
        "tx.file_intent.complete", {"path": "a.py"}, "s1"
    ).startswith("Completed intent")
    assert (
        state_rebuilder._update_semantic_summary("tx.verify.pass", {}, "s1")
        == "Verification passed"
    )
    assert (
        state_rebuilder._update_semantic_summary("tx.verify.fail", {}, "s1")
        == "Verification failed"
    )
    assert (
        state_rebuilder._update_semantic_summary("tx.commit.done", {}, "s1")
        == "Commit completed"
    )
    assert (
        state_rebuilder._update_semantic_summary("tx.commit.fail", {}, "s1")
        == "Commit failed"
    )
    assert (
        state_rebuilder._update_semantic_summary("tx.end.done", {}, "s1")
        == "Transaction ended"
    )


def test_apply_tx_event_to_state_updates_intents_and_states(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.file_intent.add",
            "payload": {
                "path": "a.py",
                "operation": "update",
                "purpose": "tests",
                "planned_step": "s1",
                "state": "planned",
            },
            "step_id": "s1",
            "seq": 1,
            "phase": "in-progress",
        },
    )
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.file_intent.update",
            "payload": {"path": "a.py", "state": "applied"},
            "step_id": "s1",
            "seq": 2,
            "phase": "in-progress",
        },
    )
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {"event_type": "tx.verify.start", "payload": {"command": "verify"}},
    )
    state_rebuilder._apply_tx_event_to_state(
        active_tx, {"event_type": "tx.verify.pass", "payload": {"ok": True}}
    )
    state_rebuilder._apply_tx_event_to_state(
        active_tx, {"event_type": "tx.commit.start", "payload": {"message": "m"}}
    )
    state_rebuilder._apply_tx_event_to_state(
        active_tx, {"event_type": "tx.commit.done", "payload": {"sha": "abc"}}
    )

    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["_last_event_seq"] == 2


def test_derive_next_action_in_progress_paths(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status="in-progress",
            verify_state={"status": "not_started"},
            commit_state={"status": "not_started"},
            active_tx={"tx_id": 1, "ticket_id": "t-1", "phase": "in-progress"},
            semantic_summary="",
        )
        == "tx.verify.start"
    )

    assert (
        state_rebuilder._derive_next_action(
            status="in-progress",
            verify_state={"status": "not_started"},
            commit_state={"status": "not_started"},
            active_tx={"tx_id": 1, "ticket_id": "t-1", "phase": "in-progress"},
            semantic_summary="verify now",
        )
        == "tx.verify.start"
    )


def test_read_tx_event_log_missing_path_returns_empty(state_rebuilder, tmp_path):
    path = tmp_path / "missing.jsonl"
    result = state_rebuilder.read_tx_event_log(start_seq=0, event_log_path=path)
    assert result["events"] == []
    assert result["invalid_lines"] == 0
    assert result["path"] == str(path)


def test_read_recent_tx_events_skips_invalid_lines(state_rebuilder, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps(["not", "dict"]),
                json.dumps({"seq": 1, "event_type": "tx.begin"}),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    events = state_rebuilder.read_recent_tx_events(5)
    assert len(events) == 1
    assert events[0]["seq"] == 1


def test_validate_tx_event_additional_cases(state_rebuilder):
    valid, _ = state_rebuilder._validate_tx_event(
        {
            "seq": 1,
            "tx_id": 1,
            "ticket_id": "t-1",
            "event_type": "tx.unknown",
            "phase": "in-progress",
            "step_id": "s1",
            "actor": {},
            "session_id": "s1",
            "payload": {},
        }
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event(
        {
            "seq": 1,
            "tx_id": 1,
            "ticket_id": "t-1",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "s1",
            "actor": {},
            "session_id": "s1",
            "payload": {},
        }
    )
    assert valid is True


def test_validate_tx_event_payload_more_cases(state_rebuilder):
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.verify.pass", {"ok": True}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.verify.fail", {"ok": False}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.fail", {"error": "nope"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.end.blocked", {"reason": "waiting"}, "s1"
    )
    assert ok is True
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.user_intent.set", {"user_intent": "continue"}, "s1"
    )
    assert ok is True


def test_validate_tx_event_invariants_success_and_terminal(state_rebuilder):
    context = state_rebuilder._init_tx_context()

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {"path": "a.py", "planned_step": "s1", "state": "planned"},
        },
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.update",
            "step_id": "s1",
            "payload": {"path": "a.py", "state": "applied"},
        },
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.verify.start", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.verify.pass", "step_id": "s1", "payload": {"ok": True}},
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.commit.start", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.commit.done", "step_id": "s1", "payload": {}}
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.end.done", "step_id": "s1", "payload": {"summary": "ok"}},
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s2", "payload": {}}
    )
    assert valid is False


def test_validate_tx_event_invariants_duplicate_intent(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {"path": "a.py", "planned_step": "s1", "state": "planned"},
        },
    )
    assert valid is True

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {"path": "a.py", "planned_step": "s1", "state": "planned"},
        },
    )
    assert valid is False


def test_read_first_event_with_ts_missing_path(state_rebuilder, tmp_path):
    missing = tmp_path / "missing.jsonl"
    assert state_rebuilder.read_first_event_with_ts(missing) is None


def test_rotate_journal_no_valid_timestamps(state_rebuilder, repo_context):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"ts": "bad"}),
                json.dumps(["not", "dict"]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is False
    assert result["reason"] == "no valid journal timestamps"


def test_rotate_journal_current_week_only(state_rebuilder, repo_context):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)

    current_week = state_rebuilder.week_start_utc(datetime.now(timezone.utc))
    current_week_ts = (current_week + timedelta(hours=1)).isoformat()

    journal.write_text(
        json.dumps({"ts": current_week_ts, "event": "current"}) + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is True
    assert result["rotated"] is False
    assert result["reason"] == "current week only"


def test_rotate_journal_no_last_week_events(state_rebuilder, repo_context):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)

    current_week = state_rebuilder.week_start_utc(datetime.now(timezone.utc))
    two_weeks_ago = current_week - timedelta(days=14)
    old_ts = (two_weeks_ago + timedelta(hours=1)).isoformat()

    journal.write_text(
        json.dumps({"ts": old_ts, "event": "old"}) + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is True
    assert result["rotated"] is False
    assert result["reason"] == "no last-week events"


def test_init_replay_state_applied_event_ids_non_list(state_rebuilder):
    state = state_rebuilder.init_replay_state({"applied_event_ids": "nope"})
    assert state["applied_event_ids"] == []


def test_select_target_session_id_latest_any(state_rebuilder):
    events = [
        {"seq": 1, "session_id": "s1"},
        {"seq": 2, "session_id": "s2"},
    ]
    assert state_rebuilder.select_target_session_id(events, None) == "s2"


def test_append_applied_event_id_initializes(state_rebuilder):
    state = {"applied_event_ids": "nope"}
    state_rebuilder.append_applied_event_id(state, "e1", max_size=2)
    assert state["applied_event_ids"] == ["e1"]


def test_apply_event_to_state_edge_branches(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)

    state_rebuilder.apply_event_to_state(
        state, {"kind": "task.update", "session_id": "s1", "payload": {}}
    )
    assert state["current_task"] == "unknown"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "task.end", "session_id": "s1", "payload": {}}
    )
    assert state["current_task"] == ""

    state_rebuilder.apply_event_to_state(
        state,
        {"kind": "task.progress", "session_id": "s1", "payload": {"status": "ready"}},
    )
    assert state["last_action"] == "task progress"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "task.blocked", "session_id": "s1", "payload": {}}
    )
    assert state["last_action"] == "task blocked"

    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.end",
            "session_id": "s1",
            "payload": {"ok": True, "returncode": 0},
        },
    )
    assert state["verification_status"] == "passed"

    state_rebuilder.apply_event_to_state(
        state,
        {"kind": "commit.end", "session_id": "s1", "payload": {"summary": "done"}},
    )
    assert state["last_commit"] == "done"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "tool.result", "session_id": "s1", "payload": {"ok": True}}
    )


def test_apply_tx_event_to_state_handles_tx_begin(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(0, "none", "planned", "none")
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.begin",
            "tx_id": 1,
            "ticket_id": "t-1",
            "step_id": "s1",
        },
    )
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"


def test_derive_next_action_checking_not_started(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status="checking",
            verify_state={"status": "not_started"},
            commit_state={"status": "not_started"},
            active_tx={"tx_id": 1, "ticket_id": "t-1", "phase": "checking"},
            semantic_summary="",
        )
        == "tx.verify.start"
    )


def test_intent_state_rank_non_str(state_rebuilder):
    assert state_rebuilder._intent_state_rank(None) == -1


def test_validate_tx_event_missing_required_fields(state_rebuilder):
    cases = [
        ({"seq": 1}, "missing tx_id"),
        (
            {
                "seq": 1,
                "tx_id": 1,
            },
            "missing ticket_id",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
            },
            "missing event_type",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
            },
            "missing phase",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
                "phase": "in-progress",
            },
            "missing step_id",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
                "phase": "in-progress",
                "step_id": "s1",
            },
            "missing actor",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
                "phase": "in-progress",
                "step_id": "s1",
                "actor": {},
            },
            "missing session_id",
        ),
        (
            {
                "seq": 1,
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
                "phase": "in-progress",
                "step_id": "s1",
                "actor": {},
                "session_id": "s1",
            },
            "missing payload",
        ),
    ]

    for event, _reason in cases:
        valid, _ = state_rebuilder._validate_tx_event(event)
        assert valid is False


def test_validate_tx_event_payload_missing_fields(state_rebuilder):
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "a.py",
            "operation": "update",
            "planned_step": "s1",
            "state": "planned",
        },
        "s1",
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {"path": "a.py", "operation": "update", "purpose": "tests", "state": "planned"},
        "s1",
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "tests",
            "planned_step": "s1",
            "state": "started",
        },
        "s1",
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.update", {"state": "started"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.complete", {"state": "verified"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.verify.pass", {"ok": False}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.verify.fail", {"ok": True}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.start", {"message": "m", "branch": "main"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.start", {"message": "m", "diff_summary": "diff"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.commit.done", {"sha": "abc", "branch": "main"}, "s1"
    )
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload("tx.commit.fail", {}, "s1")
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload("tx.end.blocked", {}, "s1")
    assert ok is False

    ok, _ = state_rebuilder._validate_tx_event_payload("tx.user_intent.set", {}, "s1")
    assert ok is False


def test_validate_tx_event_invariants_missing_path_and_complete(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}}
    )
    state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {"path": "a.py", "planned_step": "s1", "state": "planned"},
        },
    )

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.file_intent.update", "step_id": "s1", "payload": {}},
    )
    assert valid is False

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.complete",
            "step_id": "s1",
            "payload": {"path": "a.py", "state": "applied"},
        },
    )
    assert valid is False


def test_apply_tx_event_to_state_non_list_intents(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    active_tx["file_intents"] = "nope"
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.file_intent.add",
            "payload": {
                "path": "a.py",
                "operation": "update",
                "purpose": "tests",
                "planned_step": "s1",
                "state": "planned",
            },
            "step_id": "s1",
            "seq": 1,
            "phase": "in-progress",
        },
    )
    assert active_tx["file_intents"] == "nope"
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["_last_event_seq"] == 1


def test_replay_events_to_state_prefers_session_id(state_rebuilder):
    events = [
        {"seq": 1, "kind": "task.start", "session_id": "s1", "payload": {"title": "A"}},
        {"seq": 2, "kind": "task.start", "session_id": "s2", "payload": {"title": "B"}},
    ]
    state = state_rebuilder.replay_events_to_state(
        None, events, preferred_session_id="s2"
    )
    assert state["session_id"] == "s2"


def test_validate_tx_event_invariants_after_terminal(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.begin", "step_id": "none", "payload": {"ticket_id": "t"}},
    )
    state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.end.done", "step_id": "s1", "payload": {"summary": "ok"}},
    )

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context, {"event_type": "tx.step.enter", "step_id": "s2", "payload": {}}
    )
    assert valid is False


def test_apply_tx_event_to_state_creates_intent_on_update(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.file_intent.update",
            "payload": {"path": "a.py", "state": "started"},
            "step_id": "s1",
            "seq": 1,
            "phase": "in-progress",
        },
    )

    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["_last_event_seq"] == 1


def test_read_tx_event_log_dedupes_by_event_id_in_rebuild(repo_context, state_store):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_id="dup-1",
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "dup-1",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s3",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p4-t2-s3", "description": "dup"},
        },
    )

    rebuilder = StateRebuilder(repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["dropped_events"] == 1


def test_rebuild_tx_state_skips_terminal_transactions(repo_context, state_store):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.end.done",
        phase="done",
        payload={"summary": "complete"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "tx-2-begin",
            "tx_id": 2,
            "ticket_id": "p4-t2",
            "event_type": "tx.begin",
            "phase": "in-progress",
            "step_id": "p4-t2-s1",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
        },
    )

    rebuilder = StateRebuilder(repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["state"]["active_tx"]["tx_id"] == 2


def test_rebuild_tx_state_with_torn_event_skips_followups(repo_context, state_store):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-bad",
            "tx_id": 1,
        },
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "evt-late",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s2",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p4-t2-s2", "description": "later"},
        },
    )

    rebuilder = StateRebuilder(repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_drops_duplicate_event_ids(repo_context, state_store):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_id="dup-evt",
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 3,
            "event_id": "dup-evt",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s3",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "p4-t2-s3", "description": "dup"},
        },
    )

    rebuilder = StateRebuilder(repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["dropped_events"] == 1


def test_replay_events_to_state_ignores_other_sessions(state_rebuilder):
    events = [
        {
            "seq": 1,
            "kind": "session.start",
            "session_id": "s1",
            "payload": {},
        },
        {
            "seq": 2,
            "kind": "task.start",
            "session_id": "s1",
            "event_id": "e1",
            "payload": {"title": "Task A", "task_id": "t-1"},
        },
        {
            "seq": 3,
            "kind": "task.start",
            "session_id": "s2",
            "event_id": "e2",
            "payload": {"title": "Task B", "task_id": "t-2"},
        },
    ]

    state = state_rebuilder.replay_events_to_state(
        None, events, preferred_session_id="s2"
    )
    assert state["session_id"] == "s2"
    assert state["task_id"] == "t-2"


def test_apply_event_to_state_sets_failure_reason_from_verify_result(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.result",
            "session_id": "s1",
            "payload": {
                "ok": False,
                "returncode": 2,
                "stderr": "fail",
                "reason": "bad",
            },
        },
    )
    assert state["failure_reason"] == "bad"


def test_tx_state_integrity_rejects_invalid_fields(state_rebuilder):
    state = state_rebuilder._init_tx_state()
    state["schema_version"] = "0.3.0"
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state["schema_version"] = "0.4.0"
    state["last_applied_seq"] = "nope"
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state["last_applied_seq"] = 0
    state["integrity"] = []
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state["integrity"] = {"rebuilt_from_seq": "nope", "state_hash": ""}
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state["integrity"] = {"rebuilt_from_seq": 1, "state_hash": ""}
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state = state_rebuilder._init_tx_state()
    state["integrity"]["rebuilt_from_seq"] = 0
    state["integrity"]["active_tx_source"] = "none"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is True

    state["active_tx"] = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state = state_rebuilder._init_tx_state()
    state["active_tx"] = {
        "tx_id": 1,
        "ticket_id": "t-1",
        "phase": "in-progress",
        "_last_event_seq": 1,
    }
    state["status"] = "in-progress"
    state["next_action"] = "tx.verify.start"
    state["semantic_summary"] = "summary"
    state["last_applied_seq"] = 1
    state["integrity"]["rebuilt_from_seq"] = 1
    state["integrity"]["active_tx_source"] = "active_candidate"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 1) is True

    state = state_rebuilder._init_tx_state()
    state["integrity"]["rebuilt_from_seq"] = 0
    state["integrity"]["drift_detected"] = True
    state["integrity"]["active_tx_source"] = "none"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state["rebuild_warning"] = "duplicate tx.begin"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is True

    state["integrity"]["drift_detected"] = False
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 0) is False

    state = state_rebuilder._init_tx_state()
    state["active_tx"] = {
        "tx_id": "tx-1",
        "ticket_id": "p4-t2",
        "phase": "in-progress",
        "_last_event_seq": 1,
    }
    state["status"] = "in-progress"
    state["next_action"] = "tx.verify.start"
    state["semantic_summary"] = "summary"
    state["last_applied_seq"] = 1
    state["integrity"]["rebuilt_from_seq"] = 1
    state["integrity"]["active_tx_source"] = "invalid-source"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)
    assert state_rebuilder._tx_state_integrity_ok(state, 1) is False

    state["active_tx"]["tx_id"] = 1
    state["integrity"]["active_tx_source"] = "active_candidate"
    state["integrity"]["state_hash"] = "bad-hash"
    assert state_rebuilder._tx_state_integrity_ok(state, 1) is False


def test_init_replay_state_sanitizes_string_fields(state_rebuilder):
    state = state_rebuilder.init_replay_state(
        {
            "task_title": 123,
            "task_status": 456,
            "artifact_summary": 789,
            "last_verification": "nope",
            "failure_reason": 99,
        }
    )
    assert state["task_title"] == ""
    assert state["task_status"] == ""
    assert state["artifact_summary"] == ""
    assert state["last_verification"] == {}
    assert state["failure_reason"] == ""


def test_select_target_session_id_skips_invalid_seq(state_rebuilder):
    events = [
        {"seq": "bad", "session_id": "s1"},
        {"seq": 2, "session_id": "s2", "kind": "session.start"},
    ]
    assert state_rebuilder.select_target_session_id(events, None) == "s2"


def test_rotate_journal_tracks_invalid_lines(state_rebuilder, repo_context):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    current_week = state_rebuilder.week_start_utc(now)
    last_week_start = current_week - timedelta(days=7)

    last_week_ts = (last_week_start + timedelta(hours=1)).isoformat()
    current_week_ts = (current_week + timedelta(hours=1)).isoformat()

    journal.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"ts": "bad"}),
                json.dumps({"ts": last_week_ts, "event": "old"}),
                json.dumps({"ts": current_week_ts, "event": "new"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is True
    assert result["rotated"] is True
    assert result["invalid_json_lines"] == 1
    assert result["invalid_ts"] == 1


def test_rebuild_tx_state_breaks_on_invalid_payload(repo_context, state_store):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context,
        {
            "seq": 2,
            "event_id": "evt-bad-payload",
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "event_type": "tx.step.enter",
            "phase": "in-progress",
            "step_id": "p4-t2-s2",
            "actor": {"agent_id": "a1"},
            "session_id": "s1",
            "payload": {"step_id": "mismatch"},
        },
    )

    rebuilder = StateRebuilder(repo_context, state_store)
    rebuild = rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 2


def test_update_semantic_summary_begin_and_step(state_rebuilder):
    assert (
        state_rebuilder._update_semantic_summary("tx.begin", {"ticket_id": "t-1"}, "s1")
        == "Started transaction t-1"
    )
    assert (
        state_rebuilder._update_semantic_summary("tx.step.enter", {}, "s1")
        == "Entered step s1"
    )


def test_apply_tx_event_to_state_handles_failures(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(1, "t-1", "in-progress", "s1")
    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.verify.fail",
            "payload": {"ok": False},
            "phase": "checking",
        },
    )
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["phase"] == "checking"

    state_rebuilder._apply_tx_event_to_state(
        active_tx,
        {
            "event_type": "tx.commit.fail",
            "payload": {"error": "boom"},
            "phase": "verified",
        },
    )
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["phase"] == "verified"


def test_validate_tx_event_payload_verify_start(state_rebuilder):
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.verify.start", {"command": "verify"}, "s1"
    )
    assert ok is True


def test_resolve_path_none_uses_default(state_rebuilder, repo_context):
    resolved = state_rebuilder.resolve_path(None, repo_context.tx_event_log)
    assert resolved == repo_context.tx_event_log


def test_read_tx_event_log_end_seq_none_includes_all(state_store, state_rebuilder):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )
    events = state_rebuilder.read_tx_event_log(start_seq=0, end_seq=None)
    assert [event["seq"] for event in events["events"]] == [1, 2]


def test_derive_next_action_in_progress_verified_intents(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status="in-progress",
            verify_state={"status": "not_started"},
            commit_state={"status": "not_started"},
            active_tx={"tx_id": 1, "ticket_id": "t-1", "phase": "in-progress"},
            semantic_summary="",
        )
        == "tx.verify.start"
    )


def test_apply_event_to_state_file_edit_ignores_invalid_payload(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    state["last_action"] = "init"

    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "file.edit",
            "session_id": "s1",
            "payload": {"action": 123, "path": None},
        },
    )
    assert state["last_action"] == "init"


def test_select_target_session_id_returns_none_when_invalid(state_rebuilder):
    events = [
        {"seq": "bad", "session_id": "s1"},
        {"seq": 2, "session_id": 123},
        {"seq": 3},
    ]
    assert state_rebuilder.select_target_session_id(events, None) is None


def test_replay_events_to_state_with_no_target_session(state_rebuilder):
    events = [
        {"seq": 1, "kind": "session.start", "session_id": 123, "payload": {}},
        {"seq": 2, "kind": "task.start", "session_id": None, "payload": {"title": "A"}},
    ]
    state = state_rebuilder.replay_events_to_state(None, events)
    assert state["session_id"] == ""
    assert state["task_id"] == ""


def test_apply_event_to_state_unknown_kind_noop(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    state["last_action"] = "init"
    state_rebuilder.apply_event_to_state(
        state, {"kind": "unknown.event", "session_id": "s1", "payload": {"x": 1}}
    )
    assert state["last_action"] == "init"


def test_apply_event_to_state_tool_result_ok_does_not_set_error(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    state["last_error"] = ""
    state_rebuilder.apply_event_to_state(
        state, {"kind": "tool.result", "session_id": "s1", "payload": {"ok": True}}
    )
    assert state["last_error"] == ""
