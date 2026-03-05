import json
from datetime import datetime, timezone


def test_init_replay_state_defaults(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    assert state["session_id"] == ""
    assert state["current_phase"] == ""
    assert state["current_task"] == ""
    assert state["last_action"] == ""
    assert state["next_step"] == ""
    assert state["verification_status"] == ""
    assert state["last_commit"] == ""
    assert state["last_error"] == ""
    assert state["compact_context"] == ""
    assert state["task_id"] == ""
    assert state["task_title"] == ""
    assert state["task_status"] == ""
    assert state["plan_steps"] == []
    assert state["artifact_summary"] == ""
    assert state["last_verification"] == {}
    assert state["failure_reason"] == ""
    assert state["replay_warnings"]["invalid_lines"] == 0
    assert state["replay_warnings"]["dropped_events"] == 0
    assert state["applied_event_ids"] == []


def test_apply_event_to_state_verify_failure(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)
    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.end",
            "payload": {"ok": False, "stderr": "bad", "returncode": 1},
        },
    )
    assert state["verification_status"] == "failed"
    assert state["failure_reason"] == "bad"
    assert state["last_action"] == "verify finished"


def test_replay_events_to_state_selects_latest_session_start(state_rebuilder):
    events = [
        {
            "seq": 1,
            "event_id": "evt-1",
            "kind": "session.start",
            "session_id": "s1",
            "payload": {"note": "boot"},
        },
        {
            "seq": 2,
            "event_id": "evt-2",
            "kind": "session.start",
            "session_id": "s2",
            "payload": {"note": "boot2"},
        },
        {
            "seq": 3,
            "event_id": "evt-3",
            "kind": "task.start",
            "session_id": "s2",
            "payload": {"title": "Work"},
        },
    ]
    state = state_rebuilder.replay_events_to_state(snapshot_state=None, events=events)
    assert state["session_id"] == "s2"
    assert state["task_title"] == "Work"
    assert state["current_task"] == "Work"


def test_roll_forward_replay_missing_checkpoint(state_rebuilder):
    replay = state_rebuilder.roll_forward_replay()
    assert replay["ok"] is False
    assert replay["reason"] == "checkpoint not found"


def test_continue_state_rebuild_uses_snapshot_and_events(
    state_rebuilder, state_store, repo_context
):
    state_store.snapshot_save(
        state={"current_phase": "session"},
        session_id="s1",
        last_applied_seq=0,
    )
    state_store.journal_append(
        kind="task.start",
        payload={"title": "Build"},
        session_id="s1",
        event_id="evt-1",
    )
    state_store.journal_append(
        kind="task.end",
        payload={"summary": "done", "next_action": "next"},
        session_id="s1",
        event_id="evt-2",
    )
    state_store.checkpoint_update(
        last_applied_seq=0, snapshot_path=repo_context.snapshot.name
    )

    rebuilt = state_rebuilder.continue_state_rebuild(session_id="s1")
    assert rebuilt["ok"] is True
    state = rebuilt["state"]
    assert state["task_status"] == "done"
    assert state["last_action"] == "done"
    assert state["next_step"] == "next"
    assert state["current_task"] == ""


def test_read_journal_events_handles_invalid_lines(repo_context, state_rebuilder):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"foo": "bar"}),
                json.dumps({"seq": 1, "kind": "task.start"}),
                json.dumps({"seq": 2, "kind": "task.end"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.read_journal_events(start_seq=1, end_seq=2)

    assert result["invalid_lines"] == 2
    assert [event["seq"] for event in result["events"]] == [2]
    assert result["last_seq"] == 2


def test_read_recent_journal_events_filters_session(repo_context, state_rebuilder):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                json.dumps({"seq": 1, "session_id": "s1", "kind": "task.start"}),
                json.dumps({"seq": 2, "session_id": "s2", "kind": "task.start"}),
                json.dumps({"seq": 3, "session_id": "s1", "kind": "task.end"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = state_rebuilder.read_recent_journal_events(max_events=5, session_id="s1")
    assert [event["seq"] for event in events] == [1, 3]


def test_parse_iso_ts_and_week_start(state_rebuilder):
    parsed = state_rebuilder.parse_iso_ts("2026-03-02T12:00:00Z")
    assert parsed == datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert state_rebuilder.parse_iso_ts("not-a-ts") is None

    week_start = state_rebuilder.week_start_utc(parsed)
    assert week_start.weekday() == 0
    assert week_start.hour == 0
    assert week_start.minute == 0


def test_rotate_journal_if_prev_week_missing_journal(state_rebuilder):
    result = state_rebuilder.rotate_journal_if_prev_week()
    assert result["ok"] is False
    assert result["reason"] == "journal not found"


def test_rotate_journal_if_prev_week_current_week(repo_context, state_rebuilder):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps({"seq": 1, "ts": datetime.now(timezone.utc).isoformat()}) + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()

    assert result["ok"] is True
    assert result["rotated"] is False
    assert result["reason"] == "current week only"


def test_rotate_journal_if_prev_week_no_valid_ts(repo_context, state_rebuilder):
    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps({"seq": 1}),
                json.dumps({"seq": 2, "ts": "not-a-ts"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()

    assert result["ok"] is False
    assert result["reason"] == "no valid journal timestamps"


def test_rotate_journal_if_prev_week_archives_last_week(
    repo_context, state_rebuilder, monkeypatch
):
    import agentops_mcp_server.state_rebuilder as state_rebuilder_module

    journal = repo_context.journal
    journal.parent.mkdir(parents=True, exist_ok=True)

    last_week_event = {"ts": "2026-03-04T10:00:00+00:00", "seq": 1}
    current_week_event = {"ts": "2026-03-09T01:00:00+00:00", "seq": 2}

    journal.write_text(
        "\n".join([json.dumps(last_week_event), json.dumps(current_week_event)]) + "\n",
        encoding="utf-8",
    )

    fixed_now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(state_rebuilder_module, "datetime", FixedDateTime)

    result = state_rebuilder.rotate_journal_if_prev_week()

    assert result["ok"] is True
    assert result["rotated"] is True

    archive = journal.with_name("journal.20260302-20260308.jsonl")
    assert archive.exists()

    archive_lines = archive.read_text(encoding="utf-8").splitlines()
    assert archive_lines == [json.dumps(last_week_event)]


def test_apply_event_to_state_additional_branches(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)

    state_rebuilder.apply_event_to_state(
        state, {"kind": "session.start", "session_id": "s1", "payload": {}}
    )
    assert state["session_id"] == "s1"

    state_rebuilder.apply_event_to_state(
        state,
        {"kind": "task.created", "payload": {"task_id": "t-1", "title": "Build"}},
    )
    assert state["task_id"] == "t-1"
    assert state["task_title"] == "Build"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "task.progress", "payload": {"status": "blocked"}}
    )
    assert state["task_status"] == "blocked"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "task.blocked", "payload": {"reason": "waiting"}}
    )
    assert state["failure_reason"] == "waiting"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "plan.start", "payload": {"steps": ["one"]}}
    )
    state_rebuilder.apply_event_to_state(
        state, {"kind": "plan.step", "payload": {"step": "two"}}
    )
    state_rebuilder.apply_event_to_state(state, {"kind": "plan.end", "payload": {}})
    assert state["plan_steps"] == ["one", "two"]

    state_rebuilder.apply_event_to_state(
        state, {"kind": "artifact.summary", "payload": {"summary": "done"}}
    )
    assert state["artifact_summary"] == "done"

    state_rebuilder.apply_event_to_state(state, {"kind": "verify.start", "payload": {}})
    assert state["verification_status"] == "running"

    state_rebuilder.apply_event_to_state(
        state,
        {
            "kind": "verify.result",
            "payload": {"ok": False, "stderr": "failed", "returncode": 1},
        },
    )
    assert state["last_verification"]["ok"] is False
    assert state["failure_reason"] == "failed"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "commit.start", "payload": {"message": "msg"}}
    )
    assert state["last_commit"] == "msg"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "commit.end", "payload": {"sha": "abc", "summary": "sum"}}
    )
    assert state["last_commit"] == "abc"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "file.edit", "payload": {"action": "edit", "path": "a.py"}}
    )
    assert state["last_action"] == "file edit: a.py"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "tool.result", "payload": {"ok": False, "error": "boom"}}
    )
    assert state["last_error"] == "boom"

    state_rebuilder.apply_event_to_state(
        state, {"kind": "error", "payload": {"message": "bad"}}
    )
    assert state["last_error"] == "bad"


def test_append_applied_event_id_trims(state_rebuilder):
    state = {"applied_event_ids": ["evt-1", "evt-2"]}
    state_rebuilder.append_applied_event_id(state, "evt-3", max_size=2)
    assert state["applied_event_ids"] == ["evt-2", "evt-3"]
