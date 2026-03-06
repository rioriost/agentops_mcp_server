import json
from datetime import datetime, timezone

import pytest


def _append_tx_event(state_store, **overrides):
    base = {
        "tx_id": "tx-1",
        "ticket_id": "p4-t2",
        "event_type": "tx.begin",
        "phase": "in-progress",
        "step_id": "p4-t2-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"note": "start"},
    }
    base.update(overrides)
    return state_store.tx_event_append(**base)


def _append_invalid_tx_event(repo_context, event):
    with repo_context.tx_event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


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


def test_rebuild_tx_state_deterministic_hash(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store, event_type="tx.step.enter", step_id="p4-t2-s2", payload={}
    )
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.add",
        payload={
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t2-s2",
            "state": "planned",
        },
    )

    rebuild1 = state_rebuilder.rebuild_tx_state()
    rebuild2 = state_rebuilder.rebuild_tx_state()

    assert rebuild1["ok"] is True
    assert rebuild2["ok"] is True
    assert (
        rebuild1["state"]["integrity"]["state_hash"]
        == rebuild2["state"]["integrity"]["state_hash"]
    )
    assert rebuild1["last_applied_seq"] == rebuild2["last_applied_seq"]


def test_rebuild_tx_state_torn_event_truncates(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)
    _append_invalid_tx_event(
        repo_context, {"seq": 2, "event_id": "evt-bad", "tx_id": "tx-1"}
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_integrity_mismatch_rebuilds(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)

    bad_state = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p4-t2",
            "status": "in-progress",
            "phase": "in-progress",
            "current_step": "p4-t2-s1",
            "last_completed_step": "",
            "next_action": "",
            "semantic_summary": "Saved state",
            "user_intent": None,
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
        "last_applied_seq": 1,
        "integrity": {"state_hash": "bad-hash", "rebuilt_from_seq": 1},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    state_store.tx_state_save(bad_state)

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["source"] == "rebuild"
    assert rebuild["state"]["integrity"]["state_hash"] != "bad-hash"


def test_rebuild_tx_state_reconstructs_semantics_and_intent(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.user_intent.set",
        payload={"user_intent": "continue"},
    )
    _append_tx_event(
        state_store, event_type="tx.step.enter", step_id="p4-t2-s3", payload={}
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["user_intent"] == "continue"
    assert active_tx["semantic_summary"] == "Entered step p4-t2-s3"
    assert active_tx["next_action"] == "tx.verify.start"


def test_rebuild_tx_state_next_action_with_file_intents(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.add",
        payload={
            "path": "b.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t2-s4",
            "state": "planned",
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["active_tx"]["next_action"] == "continue file intents"


@pytest.mark.parametrize(
    "label, events, expected_action, expected_intent",
    [
        (
            "begin_only",
            [
                {},
            ],
            "tx.verify.start",
            None,
        ),
        (
            "intent_planned",
            [
                {},
                {
                    "event_type": "tx.file_intent.add",
                    "payload": {
                        "path": "alpha.py",
                        "operation": "update",
                        "purpose": "matrix test",
                        "planned_step": "p4-t5-s1",
                        "state": "planned",
                    },
                },
            ],
            "continue file intents",
            None,
        ),
        (
            "intent_applied",
            [
                {},
                {
                    "event_type": "tx.file_intent.add",
                    "payload": {
                        "path": "beta.py",
                        "operation": "update",
                        "purpose": "matrix test",
                        "planned_step": "p4-t5-s2",
                        "state": "applied",
                    },
                },
            ],
            "tx.verify.start",
            None,
        ),
        (
            "verify_failed_continue",
            [
                {},
                {
                    "event_type": "tx.user_intent.set",
                    "phase": "checking",
                    "payload": {"user_intent": "continue"},
                },
                {
                    "event_type": "tx.verify.fail",
                    "phase": "checking",
                    "payload": {"ok": False, "returncode": 1, "error": "nope"},
                },
            ],
            "fix and re-verify",
            "continue",
        ),
        (
            "verified_ready_to_commit",
            [
                {},
                {
                    "event_type": "tx.verify.pass",
                    "phase": "verified",
                    "payload": {"ok": True, "returncode": 0, "summary": "ok"},
                },
            ],
            "tx.commit.start",
            None,
        ),
        (
            "committed_done",
            [
                {},
                {
                    "event_type": "tx.commit.done",
                    "phase": "committed",
                    "payload": {"sha": "abc123", "summary": "done"},
                },
            ],
            "tx.end.done",
            None,
        ),
    ],
)
def test_rebuild_tx_state_interruption_matrix_next_action(
    state_rebuilder,
    state_store,
    repo_context,
    label,
    events,
    expected_action,
    expected_intent,
):
    if repo_context.tx_event_log.exists():
        repo_context.tx_event_log.write_text("", encoding="utf-8")
    if repo_context.tx_state.exists():
        repo_context.tx_state.unlink()

    for overrides in events:
        _append_tx_event(
            state_store,
            step_id="p4-t5-s1",
            phase=overrides.get("phase", "in-progress"),
            **{k: v for k, v in overrides.items() if k != "phase"},
        )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["next_action"] == expected_action
    if expected_intent is not None:
        assert active_tx["user_intent"] == expected_intent


def test_rebuild_tx_state_missing_file_intent_truncates(
    state_rebuilder, state_store, repo_context
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.update",
        payload={"path": "missing.py", "state": "started"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_append_applied_event_id_trims(state_rebuilder):
    state = {"applied_event_ids": ["evt-1", "evt-2"]}
    state_rebuilder.append_applied_event_id(state, "evt-3", max_size=2)
    assert state["applied_event_ids"] == ["evt-2", "evt-3"]
