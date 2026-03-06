import json

import pytest


def _valid_tx_state():
    return {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": "tx-1",
            "ticket_id": "p4-t1",
            "status": "in-progress",
            "phase": "in-progress",
            "current_step": "p4-t1-s1",
            "last_completed_step": "",
            "next_action": "update tests",
            "semantic_summary": "Valid state",
            "user_intent": None,
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
        },
        "last_applied_seq": 1,
        "integrity": {"state_hash": "hash", "rebuilt_from_seq": 1},
    }


def _base_tx_event_args():
    return {
        "tx_id": "tx-1",
        "ticket_id": "p4-t1",
        "event_type": "tx.begin",
        "phase": "in-progress",
        "step_id": "p4-t1-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"note": "start"},
    }


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


def test_tx_event_append_writes_required_fields(state_store, repo_context):
    result = state_store.tx_event_append(**_base_tx_event_args())
    assert result["ok"] is True
    assert result["seq"] == 1

    lines = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines[0]["tx_id"] == "tx-1"
    assert lines[0]["ticket_id"] == "p4-t1"
    assert lines[0]["event_type"] == "tx.begin"
    assert lines[0]["phase"] == "in-progress"
    assert lines[0]["step_id"] == "p4-t1-s1"
    assert lines[0]["actor"] == {"agent_id": "a1"}
    assert lines[0]["session_id"] == "s1"


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"tx_id": ""}, "tx_id is required"),
        ({"ticket_id": ""}, "ticket_id is required"),
        ({"event_type": ""}, "event_type is required"),
        ({"phase": ""}, "phase is required"),
        ({"step_id": ""}, "step_id is required"),
        ({"session_id": ""}, "session_id is required"),
        ({"actor": "nope"}, "actor is required"),
        ({"payload": "nope"}, "payload is required"),
    ],
)
def test_tx_event_append_requires_fields(state_store, overrides, match):
    args = _base_tx_event_args()
    args.update(overrides)
    with pytest.raises(ValueError, match=match):
        state_store.tx_event_append(**args)


def test_tx_state_save_writes_schema(state_store, repo_context):
    state = _valid_tx_state()
    result = state_store.tx_state_save(state)
    assert result["ok"] is True

    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "0.4.0"
    assert saved["last_applied_seq"] == 1
    assert saved["integrity"]["state_hash"] == "hash"
    assert saved["active_tx"]["file_intents"] == []
    assert saved["active_tx"]["semantic_summary"] == "Valid state"
    assert "user_intent" in saved["active_tx"]


def test_tx_state_save_requires_semantic_summary(state_store):
    state = _valid_tx_state()
    state["active_tx"]["semantic_summary"] = ""
    with pytest.raises(ValueError, match="active_tx.semantic_summary is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_user_intent_key(state_store):
    state = _valid_tx_state()
    state["active_tx"].pop("user_intent")
    with pytest.raises(ValueError, match="active_tx.user_intent is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_rejects_invalid_user_intent_type(state_store):
    state = _valid_tx_state()
    state["active_tx"]["user_intent"] = 123
    with pytest.raises(
        ValueError, match="active_tx.user_intent must be string or null"
    ):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_integrity_state_hash(state_store):
    state = _valid_tx_state()
    state["integrity"].pop("state_hash")
    with pytest.raises(ValueError, match="integrity.state_hash is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_file_intents_list(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = None
    with pytest.raises(ValueError, match="active_tx.file_intents is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_last_applied_seq(state_store):
    state = _valid_tx_state()
    state["last_applied_seq"] = "nope"
    with pytest.raises(ValueError, match="last_applied_seq is required"):
        state_store.tx_state_save(state)


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


def test_read_json_file_invalid_returns_none(state_store, repo_context):
    repo_context.snapshot.parent.mkdir(parents=True, exist_ok=True)
    repo_context.snapshot.write_text("{bad json", encoding="utf-8")

    assert state_store.read_json_file(repo_context.snapshot) is None


def test_read_last_json_line_invalid_returns_none(state_store, repo_context):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text("{bad json\n", encoding="utf-8")

    assert state_store.read_last_json_line(repo_context.journal) is None


def test_next_journal_seq_invalid_seq(state_store, repo_context):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text(
        json.dumps({"seq": "nope"}) + "\n", encoding="utf-8"
    )

    assert state_store.next_journal_seq() == 1


def test_journal_append_requires_kind(state_store):
    with pytest.raises(ValueError, match="kind is required"):
        state_store.journal_append(kind="", payload={})


def test_snapshot_save_requires_state(state_store):
    with pytest.raises(ValueError, match="state is required"):
        state_store.snapshot_save(state=None)


def test_checkpoint_update_requires_seq(state_store):
    with pytest.raises(ValueError, match="last_applied_seq is required"):
        state_store.checkpoint_update(last_applied_seq=None)


def test_write_text_creates_parent(state_store, tmp_path):
    target = tmp_path / "nested" / "file.txt"
    state_store.write_text(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


def test_snapshot_load_missing(state_store):
    result = state_store.snapshot_load()
    assert result["ok"] is False
    assert result["reason"] == "snapshot not found"


def test_checkpoint_read_missing(state_store):
    result = state_store.checkpoint_read()
    assert result["ok"] is False
    assert result["reason"] == "checkpoint not found"


def test_read_json_file_missing_returns_none(state_store, repo_context):
    missing = repo_context.snapshot.parent / "missing.json"
    assert state_store.read_json_file(missing) is None
