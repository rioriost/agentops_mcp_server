import json

import pytest

from agentops_mcp_server import main as m


@pytest.fixture
def temp_repo(tmp_path):
    original_root = m.REPO_ROOT
    m._set_repo_root(tmp_path)
    try:
        yield tmp_path
    finally:
        m._set_repo_root(original_root)


def _read_journal_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_journal_append_sequencing(temp_repo):
    result1 = m.journal_append(
        kind="session.start",
        payload={"note": "first"},
        session_id="s1",
        agent_id="a1",
        event_id="evt-1",
    )
    result2 = m.journal_append(
        kind="task.start",
        payload={"title": "Task"},
        session_id="s1",
        agent_id="a1",
    )

    assert result1["ok"] is True
    assert result2["ok"] is True
    assert result1["seq"] == 1
    assert result2["seq"] == 2
    assert result1["event_id"] == "evt-1"
    assert result2["event_id"] != "evt-1"

    lines = _read_journal_lines(m.JOURNAL)
    assert [line["seq"] for line in lines] == [1, 2]
    assert lines[0]["project_root"] == str(m.REPO_ROOT)
    assert lines[0]["kind"] == "session.start"
    assert lines[1]["kind"] == "task.start"


def test_snapshot_save_and_load(temp_repo):
    state = {"current_phase": "task", "current_task": "Test", "last_action": "working"}
    result = m.snapshot_save(
        state=state, session_id="s1", last_applied_seq=3, snapshot_id="snap-1"
    )

    assert result["ok"] is True
    assert result["snapshot_id"] == "snap-1"

    loaded = m.snapshot_load()
    assert loaded["ok"] is True
    snapshot = loaded["snapshot"]
    assert snapshot["snapshot_id"] == "snap-1"
    assert snapshot["state"] == state
    assert snapshot["session_id"] == "s1"
    assert snapshot["last_applied_seq"] == 3


def test_roll_forward_replay_missing_checkpoint(temp_repo):
    replay = m.roll_forward_replay()
    assert replay["ok"] is False
    assert replay["reason"] == "checkpoint not found"


def test_roll_forward_replay_missing_snapshot(temp_repo):
    m.checkpoint_update(last_applied_seq=0, snapshot_path="missing.json")
    replay = m.roll_forward_replay()
    assert replay["ok"] is False
    assert replay["reason"] == "snapshot not found"
    assert replay["path"].endswith("/missing.json")


def test_continue_state_rebuild_selects_latest_session(temp_repo):
    m.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )
    m.journal_append(
        kind="session.start",
        payload={"note": "first"},
        session_id="s1",
        event_id="evt-1",
    )
    m.journal_append(
        kind="session.start",
        payload={"note": "second"},
        session_id="s2",
        event_id="evt-2",
    )
    m.journal_append(
        kind="task.end",
        payload={"summary": "done", "next_action": "next up"},
        session_id="s2",
        event_id="evt-3",
    )
    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)

    rebuilt = m.continue_state_rebuild()
    assert rebuilt["ok"] is True
    state = rebuilt["state"]
    assert state["session_id"] == "s2"
    assert state["last_action"] == "done"
    assert state["next_step"] == "next up"


def test_roll_forward_replay_and_continue_state_rebuild(temp_repo):
    snapshot_state = {"current_phase": "session", "last_action": "boot"}
    m.snapshot_save(state=snapshot_state, session_id="s1", last_applied_seq=1)

    m.journal_append(
        kind="session.start",
        payload={"note": "start"},
        session_id="s1",
        event_id="evt-1",
    )
    m.journal_append(
        kind="task.start",
        payload={"title": "Write tests"},
        session_id="s1",
        event_id="evt-2",
    )
    m.journal_append(
        kind="task.end",
        payload={"summary": "done", "next_action": "next up"},
        session_id="s1",
        event_id="evt-3",
    )

    m.checkpoint_update(last_applied_seq=1, snapshot_path=m.SNAPSHOT.name)

    replay = m.roll_forward_replay()
    assert replay["ok"] is True
    assert replay["start_seq"] == 1
    assert [e["seq"] for e in replay["events"]] == [2, 3]

    rebuilt = m.continue_state_rebuild(session_id="s1")
    assert rebuilt["ok"] is True
    state = rebuilt["state"]
    assert state["session_id"] == "s1"
    assert state["current_task"] == ""
    assert state["last_action"] == "done"
    assert state["next_step"] == "next up"
    assert state["replay_warnings"]["invalid_lines"] == 0


def test_replay_state_defaults_include_extended_fields(temp_repo):
    state = m.replay_events_to_state(
        snapshot_state={"current_phase": "session"},
        events=[],
    )
    assert state["task_id"] == ""
    assert state["task_title"] == ""
    assert state["task_status"] == ""
    assert state["plan_steps"] == []
    assert state["artifact_summary"] == ""
    assert state["last_verification"] == {}
    assert state["failure_reason"] == ""


def test_continue_state_rebuild_coerces_extended_fields(temp_repo):
    snapshot_state = {
        "current_phase": "session",
        "plan_steps": "oops",
        "artifact_summary": 123,
        "last_verification": "nope",
        "failure_reason": 5,
        "task_id": None,
        "task_title": 77,
        "task_status": {},
    }
    m.snapshot_save(state=snapshot_state, session_id="s1", last_applied_seq=0)
    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)

    rebuilt = m.continue_state_rebuild(session_id="s1")
    assert rebuilt["ok"] is True
    state = rebuilt["state"]
    assert state["task_id"] == ""
    assert state["task_title"] == ""
    assert state["task_status"] == ""
    assert state["plan_steps"] == []
    assert state["artifact_summary"] == ""
    assert state["last_verification"] == {}
    assert state["failure_reason"] == ""


def test_replay_applies_extended_fields_from_events(temp_repo):
    m.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )

    m.journal_append(
        kind="task.start",
        payload={"title": "Build", "task_id": "t-1"},
        session_id="s1",
        event_id="evt-1",
    )
    m.journal_append(
        kind="plan.start",
        payload={"steps": ["one"]},
        session_id="s1",
        event_id="evt-2",
    )
    m.journal_append(
        kind="plan.step",
        payload={"step": "two"},
        session_id="s1",
        event_id="evt-3",
    )
    m.journal_append(
        kind="artifact.summary",
        payload={"summary": "done"},
        session_id="s1",
        event_id="evt-4",
    )
    m.journal_append(
        kind="verify.end",
        payload={"ok": False, "returncode": 1, "stdout": "", "stderr": "failed"},
        session_id="s1",
        event_id="evt-5",
    )
    m.journal_append(
        kind="task.blocked",
        payload={"reason": "waiting", "note": "blocked"},
        session_id="s1",
        event_id="evt-6",
    )

    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)

    rebuilt = m.continue_state_rebuild(session_id="s1")
    assert rebuilt["ok"] is True
    state = rebuilt["state"]
    assert state["task_id"] == "t-1"
    assert state["task_title"] == "Build"
    assert state["task_status"] == "blocked"
    assert state["plan_steps"] == ["one", "two"]
    assert state["artifact_summary"] == "done"
    assert state["last_verification"]["ok"] is False
    assert state["failure_reason"] == "waiting"
    assert state["last_action"] == "blocked"
