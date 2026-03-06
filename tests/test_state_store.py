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
        "payload": {"ticket_id": "p4-t1", "ticket_title": "p4-t1"},
    }


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


def test_tx_event_append_sequences(state_store, repo_context):
    result1 = state_store.tx_event_append(**_base_tx_event_args())
    result2 = state_store.tx_event_append(**_base_tx_event_args())
    assert result1["seq"] == 1
    assert result2["seq"] == 2

    lines = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [line["seq"] for line in lines] == [1, 2]


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


def test_next_tx_event_seq_invalid_seq(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps({"seq": "nope"}) + "\n", encoding="utf-8"
    )
    assert state_store.next_tx_event_seq() == 1


def test_read_last_json_line_invalid_returns_none(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("{bad json\n", encoding="utf-8")

    assert state_store.read_last_json_line(repo_context.tx_event_log) is None


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


def test_read_json_file_invalid_returns_none(state_store, repo_context):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text("{bad json", encoding="utf-8")

    assert state_store.read_json_file(repo_context.tx_state) is None


def test_read_json_file_missing_returns_none(state_store, repo_context):
    missing = repo_context.tx_state.parent / "missing.json"
    assert state_store.read_json_file(missing) is None


def test_write_text_creates_parent(state_store, tmp_path):
    target = tmp_path / "nested" / "file.txt"
    state_store.write_text(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


def test_tx_state_save_requires_schema_version_value(state_store):
    state = _valid_tx_state()
    state["schema_version"] = "0.3.0"
    with pytest.raises(ValueError, match="schema_version must be 0.4.0"):
        state_store.tx_state_save(state)


@pytest.mark.parametrize(
    "mutator, match",
    [
        (
            lambda state: state["active_tx"].update({"tx_id": ""}),
            "active_tx.tx_id is required",
        ),
        (
            lambda state: state["active_tx"].update({"ticket_id": ""}),
            "active_tx.ticket_id is required",
        ),
        (
            lambda state: state["active_tx"].update({"status": "bogus"}),
            "active_tx.status is invalid",
        ),
        (
            lambda state: state["active_tx"].update({"phase": "checking"}),
            "active_tx.phase must match status",
        ),
        (
            lambda state: state["active_tx"].update({"current_step": ""}),
            "active_tx.current_step is required",
        ),
        (
            lambda state: state["active_tx"].update({"next_action": ""}),
            "active_tx.next_action is required",
        ),
        (
            lambda state: state["active_tx"]["verify_state"].update(
                {"status": "bogus"}
            ),
            "active_tx.verify_state.status is invalid",
        ),
        (
            lambda state: state["active_tx"]["commit_state"].update(
                {"status": "bogus"}
            ),
            "active_tx.commit_state.status is invalid",
        ),
    ],
)
def test_tx_state_save_requires_active_tx_core_fields(state_store, mutator, match):
    state = _valid_tx_state()
    mutator(state)
    with pytest.raises(ValueError, match=match):
        state_store.tx_state_save(state)
