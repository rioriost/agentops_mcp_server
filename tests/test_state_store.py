import json


def test_journal_append_sequences(state_store, repo_context):
    result1 = state_store.journal_append(
        kind="session.start",
        payload={"note": "first"},
        session_id="s1",
        agent_id="a1",
        event_id="evt-1",
    )
    result2 = state_store.journal_append(
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

    lines = [
        json.loads(line)
        for line in repo_context.journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [line["seq"] for line in lines] == [1, 2]
    assert lines[0]["project_root"] == str(repo_context.get_repo_root())
    assert lines[0]["kind"] == "session.start"
    assert lines[1]["kind"] == "task.start"


def test_snapshot_save_and_load(state_store):
    state = {"current_phase": "task", "current_task": "Test", "last_action": "working"}
    result = state_store.snapshot_save(
        state=state, session_id="s1", last_applied_seq=3, snapshot_id="snap-1"
    )

    assert result["ok"] is True
    assert result["snapshot_id"] == "snap-1"

    loaded = state_store.snapshot_load()
    assert loaded["ok"] is True
    snapshot = loaded["snapshot"]
    assert snapshot["snapshot_id"] == "snap-1"
    assert snapshot["state"] == state
    assert snapshot["session_id"] == "s1"
    assert snapshot["last_applied_seq"] == 3


def test_checkpoint_update_and_read(state_store):
    result = state_store.checkpoint_update(
        last_applied_seq=5, snapshot_path="snap.json"
    )
    assert result["ok"] is True

    loaded = state_store.checkpoint_read()
    assert loaded["ok"] is True
    checkpoint = loaded["checkpoint"]
    assert checkpoint["last_applied_seq"] == 5
    assert checkpoint["snapshot_path"] == "snap.json"
