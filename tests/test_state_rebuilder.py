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
