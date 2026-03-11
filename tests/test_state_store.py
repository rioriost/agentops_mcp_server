import json

import pytest

from agentops_mcp_server.state_store import StateStore, canonical_tx_id


def _valid_tx_state():
    verify_state = {"status": "not_started", "last_result": None}
    commit_state = {"status": "not_started", "last_result": None}
    return {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t1",
            "status": "in-progress",
            "phase": "in-progress",
            "current_step": "p4-t1-s1",
            "last_completed_step": "",
            "next_action": "tx.verify.start",
            "semantic_summary": "Valid state",
            "user_intent": None,
            "session_id": "s1",
            "verify_state": verify_state,
            "commit_state": commit_state,
            "file_intents": [],
        },
        "status": "in-progress",
        "next_action": "tx.verify.start",
        "semantic_summary": "Valid state",
        "verify_state": verify_state,
        "commit_state": commit_state,
        "last_applied_seq": 1,
        "integrity": {"state_hash": "hash", "rebuilt_from_seq": 1},
        "updated_at": "2026-03-08T00:00:00+00:00",
    }


def _base_tx_event_args():
    return {
        "tx_id": 1,
        "ticket_id": "p4-t1",
        "event_type": "tx.begin",
        "phase": "in-progress",
        "step_id": "p4-t1-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"ticket_id": "p4-t1", "ticket_title": "p4-t1"},
    }


def _event_lines(repo_context):
    if not repo_context.tx_event_log.exists():
        return []
    return [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _error_lines(repo_context):
    if not repo_context.errors.exists():
        return []
    return [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_canonical_tx_id_accepts_integer_ids():
    assert canonical_tx_id(7) == 7


@pytest.mark.parametrize("value", ["7", "", None, True, False])
def test_canonical_tx_id_rejects_non_integer_ids(value):
    with pytest.raises(ValueError, match="tx_id must be an integer"):
        canonical_tx_id(value)


def test_read_json_file_missing_returns_none(state_store, repo_context):
    missing = repo_context.tx_state.parent / "missing.json"
    assert state_store.read_json_file(missing) is None


def test_read_json_file_invalid_returns_none(state_store, repo_context):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text("{bad json", encoding="utf-8")

    assert state_store.read_json_file(repo_context.tx_state) is None


def test_write_text_creates_parent(state_store, tmp_path):
    target = tmp_path / "nested" / "file.txt"
    state_store.write_text(target, "ok")
    assert target.read_text(encoding="utf-8") == "ok"


def test_append_json_line_appends_records(state_store, tmp_path):
    target = tmp_path / "nested" / "errors.jsonl"

    state_store.append_json_line(target, {"ok": False, "error": "boom"})
    state_store.append_json_line(target, {"ok": False, "error": "still boom"})

    lines = [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines == [
        {"ok": False, "error": "boom"},
        {"ok": False, "error": "still boom"},
    ]


def test_read_last_json_line_missing_returns_none(state_store, repo_context):
    assert state_store.read_last_json_line(repo_context.tx_event_log) is None


def test_read_last_json_line_invalid_returns_none(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("{bad json\n", encoding="utf-8")

    assert state_store.read_last_json_line(repo_context.tx_event_log) is None


def test_read_last_json_line_returns_last_record(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(["", json.dumps({"seq": 1}), "   ", json.dumps({"seq": 2})]) + "\n",
        encoding="utf-8",
    )

    assert state_store.read_last_json_line(repo_context.tx_event_log) == {"seq": 2}


def test_next_tx_event_seq_defaults_to_one(state_store):
    assert state_store.next_tx_event_seq() == 1


def test_next_tx_event_seq_ignores_invalid_last_seq(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps({"seq": "nope"}) + "\n", encoding="utf-8"
    )
    assert state_store.next_tx_event_seq() == 1


def test_read_tx_id_counter_missing_returns_zero_baseline(state_store):
    counter = state_store.read_tx_id_counter()

    assert counter["last_issued_id"] == 0
    assert isinstance(counter["updated_at"], str)
    assert counter["updated_at"]


def test_write_tx_id_counter_persists_payload(state_store, repo_context):
    result = state_store.write_tx_id_counter(
        {"last_issued_id": 7, "updated_at": "2026-03-10T00:00:00+00:00"}
    )

    assert result["ok"] is True
    saved = json.loads(repo_context.tx_id_counter.read_text(encoding="utf-8"))
    assert saved == {
        "last_issued_id": 7,
        "updated_at": "2026-03-10T00:00:00+00:00",
    }


def test_read_tx_id_counter_rejects_invalid_last_issued_id(state_store, repo_context):
    repo_context.tx_id_counter.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_id_counter.write_text(
        json.dumps({"last_issued_id": "7", "updated_at": "2026-03-10T00:00:00+00:00"})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="tx_id_counter.last_issued_id must be an integer"
    ):
        state_store.read_tx_id_counter()


def test_issue_tx_id_persists_monotonic_integer_ids(state_store, repo_context):
    first = state_store.issue_tx_id()
    second = state_store.issue_tx_id()

    assert first == 1
    assert second == 2

    saved = json.loads(repo_context.tx_id_counter.read_text(encoding="utf-8"))
    assert saved["last_issued_id"] == 2
    assert isinstance(saved["updated_at"], str)
    assert saved["updated_at"]


def test_tx_state_save_writes_schema_and_top_level_fields(state_store, repo_context):
    state = _valid_tx_state()

    result = state_store.tx_state_save(state)

    assert result["ok"] is True
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "0.4.0"
    assert saved["status"] == "in-progress"
    assert saved["next_action"] == "tx.verify.start"
    assert saved["semantic_summary"] == "Valid state"
    assert saved["verify_state"]["status"] == "not_started"
    assert saved["commit_state"]["status"] == "not_started"
    assert saved["active_tx"]["tx_id"] == 1
    assert saved["active_tx"]["ticket_id"] == "p4-t1"
    assert saved["active_tx"]["file_intents"] == []


def test_tx_state_save_preserves_active_tx_session_id(state_store, repo_context):
    state = _valid_tx_state()
    state["active_tx"]["session_id"] = "s1"

    result = state_store.tx_state_save(state)

    assert result["ok"] is True
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["active_tx"]["session_id"] == "s1"


def test_tx_state_save_sets_updated_at_when_missing(state_store, repo_context):
    state = _valid_tx_state()
    state.pop("updated_at")

    result = state_store.tx_state_save(state)

    assert result["ok"] is True
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert isinstance(saved["updated_at"], str)
    assert saved["updated_at"]


def test_tx_state_save_rejects_none_state(state_store):
    with pytest.raises(ValueError, match="state is required"):
        state_store.tx_state_save(None)


def test_tx_state_save_requires_schema_version(state_store):
    state = _valid_tx_state()
    state["schema_version"] = "0.3.0"

    with pytest.raises(ValueError, match="schema_version must be 0.4.0"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_last_applied_seq(state_store):
    state = _valid_tx_state()
    state["last_applied_seq"] = "nope"

    with pytest.raises(ValueError, match="last_applied_seq is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_integrity_state_hash(state_store):
    state = _valid_tx_state()
    state["integrity"].pop("state_hash")

    with pytest.raises(ValueError, match="integrity.state_hash is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_requires_integrity_rebuilt_from_seq(state_store):
    state = _valid_tx_state()
    state["integrity"].pop("rebuilt_from_seq")

    with pytest.raises(ValueError, match="integrity.rebuilt_from_seq is required"):
        state_store.tx_state_save(state)


def test_tx_state_save_uses_top_level_semantic_summary_for_validation(state_store):
    state = _valid_tx_state()
    state["active_tx"]["semantic_summary"] = ""

    result = state_store.tx_state_save(state)

    assert result["ok"] is True


def test_tx_state_save_allows_missing_active_tx_user_intent_key(state_store):
    state = _valid_tx_state()
    state["active_tx"].pop("user_intent")

    result = state_store.tx_state_save(state)

    assert result["ok"] is True


def test_tx_state_save_allows_non_string_active_tx_user_intent_type(state_store):
    state = _valid_tx_state()
    state["active_tx"]["user_intent"] = 123

    result = state_store.tx_state_save(state)

    assert result["ok"] is True


def test_tx_state_save_allows_missing_active_tx_file_intents_list(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = None

    result = state_store.tx_state_save(state)

    assert result["ok"] is True


@pytest.mark.parametrize(
    "mutator, match",
    [
        (
            lambda state: state["active_tx"].update({"tx_id": ""}),
            "active_tx.tx_id must be an integer",
        ),
        (
            lambda state: state["active_tx"].update({"ticket_id": ""}),
            "active_tx.ticket_id is required",
        ),
        (
            lambda state: state.update({"status": "bogus"}),
            "status is invalid",
        ),
        (
            lambda state: state.update({"next_action": ""}),
            "next_action is required",
        ),
        (
            lambda state: state.update({"semantic_summary": ""}),
            "semantic_summary is required",
        ),
        (
            lambda state: state.update({"verify_state": {"status": "bogus"}}),
            "verify_state.status is invalid",
        ),
        (
            lambda state: state.update({"commit_state": {"status": "bogus"}}),
            "commit_state.status is invalid",
        ),
    ],
)
def test_tx_state_save_requires_current_top_level_contract(state_store, mutator, match):
    state = _valid_tx_state()
    mutator(state)

    with pytest.raises(ValueError, match=match):
        state_store.tx_state_save(state)


def test_validate_tx_state_requires_updated_at(state_store):
    state = _valid_tx_state()
    state.pop("updated_at")

    with pytest.raises(ValueError, match="updated_at is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_null_top_level_fields_when_active_tx_is_null(
    state_store,
):
    state = _valid_tx_state()
    state["active_tx"] = None

    with pytest.raises(ValueError, match="status must be null when active_tx is null"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_rejects_invalid_top_level_status(state_store):
    state = _valid_tx_state()
    state["status"] = "bogus"

    with pytest.raises(ValueError, match="status is invalid"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_top_level_verify_state_dict(state_store):
    state = _valid_tx_state()
    state["verify_state"] = "bad"

    with pytest.raises(ValueError, match="verify_state must be an object or null"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_top_level_commit_state_dict(state_store):
    state = _valid_tx_state()
    state["commit_state"] = "bad"

    with pytest.raises(ValueError, match="commit_state must be an object or null"):
        state_store._validate_tx_state(state)


def test_tx_event_append_writes_required_fields(state_store, repo_context):
    result = state_store.tx_event_append(**_base_tx_event_args())

    assert result["ok"] is True
    assert result["seq"] == 1

    lines = _event_lines(repo_context)
    assert lines[0]["tx_id"] == 1
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
    assert [line["seq"] for line in _event_lines(repo_context)] == [1, 2]


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"tx_id": ""}, "tx_id must be an integer"),
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


def test_tx_event_append_rejects_unknown_event_type(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.unknown"

    with pytest.raises(ValueError, match="event_type is not defined in taxonomy"):
        state_store.tx_event_append(**args)


def test_tx_event_append_requires_tx_begin_when_no_state(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.start"
    args["payload"] = {}

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        state_store.tx_event_append(**args)


def test_tx_event_append_allows_tx_begin_when_event_log_empty(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    result = state_store.tx_event_append(**_base_tx_event_args())
    assert result["ok"] is True


def test_tx_event_append_rejects_tx_begin_when_active_tx_in_progress_and_log_not_empty(
    state_store, repo_context
):
    state = _valid_tx_state()
    state_store.tx_state_save(state)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps({"seq": 1}) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="active transaction already in progress"):
        state_store.tx_event_append(**_base_tx_event_args())


def test_tx_event_append_rejects_mismatched_active_transaction(state_store):
    state = _valid_tx_state()
    state["active_tx"]["tx_id"] = 7
    state["active_tx"]["ticket_id"] = "p4-t-active"
    state["active_tx"]["current_step"] = "p4-t-active-s1"
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args.update(
        {
            "tx_id": 8,
            "ticket_id": "p4-t-requested",
            "event_type": "tx.step.enter",
            "step_id": "p4-t-requested-s1",
            "payload": {
                "step_id": "p4-t-requested-s1",
                "description": "task started",
            },
        }
    )

    with pytest.raises(
        ValueError,
        match="tx_id does not match active transaction: active_tx=7, requested_tx=8",
    ):
        state_store.tx_event_append(**args)


def test_tx_event_append_rejects_event_after_terminal(state_store):
    state = _valid_tx_state()
    state["active_tx"]["status"] = "done"
    state["active_tx"]["phase"] = "done"
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.step.enter"
    args["payload"] = {"step_id": "p4-t1-s1", "description": "step"}

    with pytest.raises(ValueError, match="event after terminal"):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_add_rejects_invalid_operation(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.add"
    args["payload"] = {
        "path": "a.py",
        "operation": "invalid",
        "purpose": "update tests",
        "planned_step": "p4-t1-s1",
        "state": "planned",
    }

    with pytest.raises(ValueError, match="payload.operation is invalid"):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_add_requires_matching_current_step(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.add"
    args["payload"] = {
        "path": "a.py",
        "operation": "update",
        "purpose": "update tests",
        "planned_step": "different-step",
        "state": "planned",
    }

    with pytest.raises(ValueError, match="planned_step must match current_step"):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_add_rejects_duplicate_path(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = [
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t1-s1",
            "state": "planned",
            "last_event_seq": 0,
        }
    ]
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.add"
    args["payload"] = {
        "path": "a.py",
        "operation": "update",
        "purpose": "update tests",
        "planned_step": "p4-t1-s1",
        "state": "planned",
    }

    with pytest.raises(ValueError, match="file intent already exists for path"):
        state_store.tx_event_append(**args)


def test_tx_event_append_requires_intent_before_update(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "missing.py", "state": "started"}

    with pytest.raises(ValueError, match="file intent missing for path"):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_update_requires_monotonic_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = [
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t1-s1",
            "state": "applied",
            "last_event_seq": 0,
        }
    ]
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "a.py", "state": "started"}

    with pytest.raises(ValueError, match="file intent state must be monotonic"):
        state_store.tx_event_append(**args)


def test_tx_event_append_verify_requires_applied_intents(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = [
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t1-s1",
            "state": "planned",
            "last_event_seq": 0,
        }
    ]
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.start"
    args["payload"] = {}

    with pytest.raises(ValueError, match="verify.start requires applied intents"):
        state_store.tx_event_append(**args)


def test_tx_event_append_verify_pass_requires_running_state(state_store):
    state = _valid_tx_state()
    state["verify_state"] = {"status": "not_started", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.pass"
    args["payload"] = {"ok": True}

    with pytest.raises(ValueError, match="verify result requires verify.start"):
        state_store.tx_event_append(**args)


def test_tx_event_append_allows_verify_pass_when_running(state_store):
    state = _valid_tx_state()
    state["verify_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.pass"
    args["payload"] = {"ok": True}

    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_commit_requires_verify_pass(state_store):
    state = _valid_tx_state()
    state["verify_state"] = {"status": "failed", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.start"
    args["payload"] = {
        "message": "commit",
        "branch": "main",
        "diff_summary": "diff",
    }

    with pytest.raises(ValueError, match="commit.start requires verify.pass"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_done_requires_running_commit_state(state_store):
    state = _valid_tx_state()
    state["commit_state"] = {"status": "not_started", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.done"
    args["payload"] = {"sha": "sha", "branch": "main", "diff_summary": "diff"}

    with pytest.raises(ValueError, match="commit result requires commit.start"):
        state_store.tx_event_append(**args)


def test_tx_event_append_allows_commit_done_when_running(state_store):
    state = _valid_tx_state()
    state["commit_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.done"
    args["payload"] = {"sha": "sha", "branch": "main", "diff_summary": "diff"}

    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_requires_verify_pass_for_verified_intent(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = [
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t1-s1",
            "state": "applied",
            "last_event_seq": 0,
        }
    ]
    state["verify_state"] = {"status": "failed", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "a.py", "state": "verified"}

    with pytest.raises(ValueError, match="file intent verified requires verify.pass"):
        state_store.tx_event_append(**args)


def test_tx_event_append_and_state_save_succeeds_for_current_contract(
    state_store, repo_context
):
    state = _valid_tx_state()

    result = state_store.tx_event_append_and_state_save(
        **_base_tx_event_args(),
        state=state,
    )

    assert result["ok"] is True
    assert result["seq"] == 1

    assert [event["event_type"] for event in _event_lines(repo_context)] == ["tx.begin"]
    assert _error_lines(repo_context) == []


def test_tx_event_append_and_state_save_logs_explicit_state_save_failure(
    state_store, repo_context, monkeypatch
):
    state = _valid_tx_state()

    def failing_tx_state_save(_state):
        raise ValueError("forced tx_state save failure")

    monkeypatch.setattr(state_store, "tx_state_save", failing_tx_state_save)

    with pytest.raises(
        RuntimeError,
        match="canonical event appended but tx_state synchronization failed",
    ):
        state_store.tx_event_append_and_state_save(
            **_base_tx_event_args(),
            state=state,
        )

    assert [event["event_type"] for event in _event_lines(repo_context)] == ["tx.begin"]
    errors = _error_lines(repo_context)
    assert len(errors) == 1
    assert errors[0]["tool_name"] == "tx_event_append_and_state_save"
    assert errors[0]["tool_output"]["reason"] == "forced tx_state save failure"


def test_tx_event_append_and_state_save_logs_reload_failure(
    state_store, repo_context, monkeypatch
):
    state = _valid_tx_state()
    original_read_json_file = state_store.read_json_file

    def unreadable_saved_state(path):
        if path == repo_context.tx_state:
            return []
        return original_read_json_file(path)

    monkeypatch.setattr(state_store, "read_json_file", unreadable_saved_state)

    with pytest.raises(
        RuntimeError,
        match="canonical event appended but tx_state synchronization could not be verified",
    ):
        state_store.tx_event_append_and_state_save(
            **_base_tx_event_args(),
            state=state,
        )

    errors = _error_lines(repo_context)
    assert len(errors) == 1
    assert errors[0]["tool_name"] == "tx_event_append_and_state_save"
    assert (
        errors[0]["tool_output"]["error"]
        == "event append succeeded but tx_state could not be reloaded"
    )


def test_log_tool_error_writes_errors_jsonl(state_store, repo_context):
    result = state_store.log_tool_error(
        tool_name="repo_verify",
        tool_input={"timeout_sec": 30},
        tool_output={"error": "verify failed"},
    )

    assert result["ok"] is True
    assert result["path"] == str(repo_context.errors)

    lines = _error_lines(repo_context)
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "repo_verify"
    assert lines[0]["tool_input"] == {"timeout_sec": 30}
    assert lines[0]["tool_output"]["error"] == "verify failed"
    assert lines[0]["diagnostics"]["validation_point"] == "repo_verify"
    assert lines[0]["diagnostics"]["event_sequence"] == {"last_logged_seq": None}


def test_log_tool_error_writes_structured_sync_diagnostics(state_store, repo_context):
    tool_input = {
        "tx_id": "tx-7",
        "ticket_id": "p2-t04",
        "validation_point": "commit_gating",
        "event_seq": 11,
    }
    tool_output = {
        "error": "commit.start requires verify.pass",
        "expected_state": {
            "verify_state": "passed",
            "commit_state": "not_started",
        },
        "observed_state": {
            "verify_state": "running",
            "commit_state": "not_started",
        },
    }

    result = state_store.log_tool_error(
        tool_name="repo_commit",
        tool_input=tool_input,
        tool_output=tool_output,
    )

    assert result["ok"] is True
    lines = _error_lines(repo_context)
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "repo_commit"
    assert lines[0]["tool_output"]["expected_state"]["verify_state"] == "passed"
    assert lines[0]["tool_output"]["observed_state"]["verify_state"] == "running"
    assert lines[0]["diagnostics"]["validation_point"] == "repo_commit"
