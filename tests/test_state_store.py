import json
from pathlib import Path

import pytest

from agentops_mcp_server.commit_manager import CommitManager
from agentops_mcp_server.repo_context import RepoContext
from agentops_mcp_server.state_rebuilder import StateRebuilder
from agentops_mcp_server.state_store import StateStore


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


class _DummyGitRepo:
    def __init__(self, status_lines=None):
        self.calls = []
        self._status_lines = status_lines or []

    def git(self, *args):
        self.calls.append(args)
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        if args == ("rev-parse", "HEAD"):
            return "abc123"
        return ""

    def status_porcelain(self):
        return self._status_lines

    def diff_stat(self):
        return "diff"

    def diff_stat_cached(self):
        return "diff"


class _DummyVerifyRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_verify(self, timeout_sec=None):
        self.calls.append(timeout_sec)
        return self.result


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


def test_tx_state_save_preserves_active_tx_session_id(state_store, repo_context):
    state = _valid_tx_state()
    state["active_tx"]["session_id"] = "s1"

    result = state_store.tx_state_save(state)

    assert result["ok"] is True
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["active_tx"]["session_id"] == "s1"


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


def test_append_json_line_appends_record(state_store, tmp_path):
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


def test_log_tool_error_writes_errors_jsonl(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)

    result = state_store.log_tool_error(
        tool_name="repo_verify",
        tool_input={"timeout_sec": 30},
        tool_output={"error": "verify failed"},
    )

    assert result["ok"] is True
    assert result["path"] == str(tmp_path / ".agent" / "errors.jsonl")

    lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "repo_verify"
    assert lines[0]["tool_input"] == {"timeout_sec": 30}
    assert lines[0]["tool_output"] == {"error": "verify failed"}
    assert isinstance(lines[0]["ts"], str)
    assert lines[0]["ts"]


def test_log_tool_error_writes_rebuild_drift_context(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)

    tool_input = {
        "start_seq": 0,
        "end_seq": None,
        "event_log_path": str(tmp_path / ".agent" / "tx_event_log.jsonl"),
    }
    tool_output = {
        "error": "no active transaction materialized despite canonical events up to a terminal boundary",
        "ts": "2026-03-08T00:00:00+00:00",
        "observed_mismatch": {
            "drift_reason": "no active transaction materialized despite canonical events up to a terminal boundary",
            "event_log_path": str(tmp_path / ".agent" / "tx_event_log.jsonl"),
            "last_applied_seq": 2,
            "active_tx_id": "none",
            "active_ticket_id": "none",
            "terminal_tx_ids": ["tx-1"],
            "known_tx_ids": ["tx-1"],
            "last_seen_event_by_tx": {"tx-1": 2},
            "begin_seq_by_tx": {"tx-1": 1},
            "last_session_by_tx": {"tx-1": "s1"},
        },
    }

    result = state_store.log_tool_error(
        tool_name="rebuild_tx_state",
        tool_input=tool_input,
        tool_output=tool_output,
    )

    assert result["ok"] is True

    lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "rebuild_tx_state"
    assert lines[0]["tool_input"] == tool_input
    assert lines[0]["tool_output"]["error"] == tool_output["error"]
    assert lines[0]["tool_output"]["observed_mismatch"]["last_applied_seq"] == 2
    assert lines[0]["tool_output"]["observed_mismatch"]["active_tx_id"] == "none"
    assert lines[0]["tool_output"]["observed_mismatch"]["active_ticket_id"] == "none"
    assert lines[0]["tool_output"]["observed_mismatch"]["terminal_tx_ids"] == ["tx-1"]
    assert lines[0]["tool_output"]["observed_mismatch"]["known_tx_ids"] == ["tx-1"]
    assert lines[0]["tool_output"]["observed_mismatch"]["last_seen_event_by_tx"] == {
        "tx-1": 2
    }
    assert lines[0]["tool_output"]["observed_mismatch"]["begin_seq_by_tx"] == {
        "tx-1": 1
    }
    assert lines[0]["tool_output"]["observed_mismatch"]["last_session_by_tx"] == {
        "tx-1": "s1"
    }


def test_log_tool_error_writes_structured_sync_diagnostics(tmp_path):
    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)

    tool_input = {
        "tx_id": "tx-7",
        "ticket_id": "p2-t04",
        "validation_point": "commit_gating",
        "event_seq": 11,
    }
    tool_output = {
        "error": "commit.start requires verify.pass",
        "diagnostic_type": "synchronization_guard_failure",
        "expected_state": {
            "verify_state": "passed",
            "commit_state": "not_started",
        },
        "observed_state": {
            "verify_state": "running",
            "commit_state": "not_started",
        },
        "active_tx": {
            "tx_id": "tx-7",
            "ticket_id": "p2-t04",
            "session_id": "s1",
        },
        "event_context": {
            "event_seq": 11,
            "event_type": "tx.commit.start",
        },
    }

    result = state_store.log_tool_error(
        tool_name="repo_commit",
        tool_input=tool_input,
        tool_output=tool_output,
    )

    assert result["ok"] is True

    lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "repo_commit"
    assert lines[0]["tool_input"] == tool_input
    assert lines[0]["tool_output"]["diagnostic_type"] == "synchronization_guard_failure"
    assert lines[0]["tool_output"]["expected_state"]["verify_state"] == "passed"
    assert lines[0]["tool_output"]["observed_state"]["verify_state"] == "running"
    assert lines[0]["tool_output"]["active_tx"]["ticket_id"] == "p2-t04"
    assert lines[0]["tool_output"]["active_tx"]["session_id"] == "s1"
    assert lines[0]["tool_output"]["event_context"]["event_seq"] == 11
    assert lines[0]["tool_output"]["event_context"]["event_type"] == "tx.commit.start"


def test_log_tool_error_requires_initialized_root(tmp_path):
    repo_context = RepoContext(Path("/"))
    state_store = StateStore(repo_context)

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        state_store.log_tool_error(
            tool_name="repo_verify",
            tool_input={"timeout_sec": 30},
            tool_output={"error": "verify failed"},
        )


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


def test_commit_manager_uses_active_tx_session_id_for_events(tmp_path, monkeypatch):
    from agentops_mcp_server.repo_context import RepoContext

    repo_context = RepoContext(tmp_path)
    state_store = state_store = __import__(
        "agentops_mcp_server.state_store", fromlist=["StateStore"]
    ).StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    state_store.tx_event_append(**_base_tx_event_args())
    rebuild = state_rebuilder.rebuild_tx_state()
    state_store.tx_state_save(rebuild["state"])

    state = _valid_tx_state()
    state["active_tx"]["session_id"] = "s1"
    state["active_tx"]["verify_state"]["status"] = "running"
    state_store.tx_state_save(state)

    manager = CommitManager(
        _DummyGitRepo(status_lines=[" M file.txt"]),
        _DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: None)

    result = manager.commit_if_verified("message", timeout_sec=5)

    assert result["sha"] == "abc123"
    events = [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    emitted = [event for event in events if event["event_type"] != "tx.begin"]
    assert emitted
    assert all(event["session_id"] == "s1" for event in emitted)


def test_commit_manager_requires_active_tx_session_id_for_event_context(tmp_path):
    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    state_rebuilder = StateRebuilder(repo_context, state_store)

    state = _valid_tx_state()
    state["active_tx"]["session_id"] = ""
    state_store.tx_state_save(state)

    manager = CommitManager(
        _DummyGitRepo(status_lines=[" M file.txt"]),
        _DummyVerifyRunner({"ok": True, "returncode": 0, "stdout": "ok"}),
        state_store,
        state_rebuilder,
    )

    assert manager._load_tx_context() is None


def test_tx_event_append_rejects_unknown_event_type(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.unknown"
    with pytest.raises(ValueError, match="event_type is not defined in taxonomy"):
        state_store.tx_event_append(**args)


def test_tx_event_append_rejects_mismatched_active_transaction(state_store):
    state = _valid_tx_state()
    state["active_tx"]["tx_id"] = "tx-active"
    state["active_tx"]["ticket_id"] = "p4-t-active"
    state["active_tx"]["current_step"] = "p4-t-active-s1"
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args.update(
        {
            "tx_id": "tx-requested",
            "ticket_id": "p4-t-requested",
            "event_type": "tx.step.enter",
            "step_id": "p4-t-requested-s1",
            "payload": {"step_id": "p4-t-requested-s1", "description": "task started"},
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: "
            "active_tx=tx-active, requested_tx=tx-requested"
        ),
    ):
        state_store.tx_event_append(**args)


def test_tx_event_append_requires_intent_before_update(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "missing.py", "state": "started"}
    with pytest.raises(ValueError, match="file intent missing for path"):
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


def test_tx_event_append_commit_requires_verify_pass(state_store):
    state = _valid_tx_state()
    state["active_tx"]["verify_state"] = {"status": "failed", "last_result": None}
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


def test_tx_event_append_requires_tx_begin_when_no_state(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.start"
    args["payload"] = {}
    with pytest.raises(ValueError, match="tx.begin required before other events"):
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
    state["active_tx"]["verify_state"] = {"status": "failed", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "a.py", "state": "verified"}
    with pytest.raises(ValueError, match="file intent verified requires verify.pass"):
        state_store.tx_event_append(**args)


def test_tx_event_append_step_enter_requires_matching_step_id(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.step.enter"
    args["payload"] = {"step_id": "different-step"}
    with pytest.raises(ValueError, match="payload.step_id must match step_id"):
        state_store.tx_event_append(**args)


def test_tx_event_append_rejects_tx_begin_when_active_tx_in_progress_and_log_not_empty(
    state_store, repo_context
):
    state = _valid_tx_state()
    state_store.tx_state_save(state)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps({"seq": 1}) + "\n", encoding="utf-8"
    )

    args = _base_tx_event_args()
    with pytest.raises(ValueError, match="active transaction already in progress"):
        state_store.tx_event_append(**args)


def test_tx_event_append_allows_tx_begin_when_active_tx_id_is_none(
    state_store, repo_context
):
    state = _valid_tx_state()
    state["active_tx"]["tx_id"] = "none"
    state["active_tx"]["ticket_id"] = "none"
    state["active_tx"]["status"] = "planned"
    state["active_tx"]["phase"] = "planned"
    state["active_tx"]["current_step"] = "none"
    state["active_tx"]["next_action"] = "tx.begin"
    state["active_tx"]["semantic_summary"] = "No active transaction."
    state_store.tx_state_save(state)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps({"seq": 1}) + "\n", encoding="utf-8"
    )

    args = _base_tx_event_args()
    args["tx_id"] = "tx-2"
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_rejects_mismatched_tx_id(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["tx_id"] = "tx-2"
    args["event_type"] = "tx.step.enter"
    args["payload"] = {"step_id": "p4-t1-s1"}
    with pytest.raises(ValueError, match="tx_id does not match active transaction"):
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


def test_tx_event_append_file_intent_add_requires_planned_state(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.add"
    args["payload"] = {
        "path": "a.py",
        "operation": "update",
        "purpose": "update tests",
        "planned_step": "p4-t1-s1",
        "state": "started",
    }
    with pytest.raises(ValueError, match="payload.state must be planned"):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_update_requires_valid_state(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "a.py", "state": "bogus"}
    with pytest.raises(
        ValueError, match="payload.state must be started, applied, or verified"
    ):
        state_store.tx_event_append(**args)


def test_tx_event_append_file_intent_complete_requires_verified_state(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.complete"
    args["payload"] = {"path": "a.py", "state": "applied"}
    with pytest.raises(ValueError, match="payload.state must be verified"):
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


def test_tx_event_append_verify_pass_requires_ok_true(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.pass"
    args["payload"] = {"ok": False}
    with pytest.raises(ValueError, match="payload.ok must be true"):
        state_store.tx_event_append(**args)


def test_tx_event_append_verify_fail_requires_ok_false(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.fail"
    args["payload"] = {"ok": True}
    with pytest.raises(ValueError, match="payload.ok must be false"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_start_requires_payload_fields(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.start"
    args["payload"] = {"message": "commit", "diff_summary": "diff"}
    with pytest.raises(ValueError, match="payload.branch is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_done_requires_payload_fields(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.done"
    args["payload"] = {"branch": "main", "diff_summary": "diff"}
    with pytest.raises(ValueError, match="payload.sha is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_fail_requires_error(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.fail"
    args["payload"] = {}
    with pytest.raises(ValueError, match="payload.error is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_end_done_requires_summary(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.end.done"
    args["payload"] = {}
    with pytest.raises(ValueError, match="payload.summary is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_end_blocked_requires_reason(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.end.blocked"
    args["payload"] = {}
    with pytest.raises(ValueError, match="payload.reason is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_user_intent_set_requires_user_intent(state_store):
    args = _base_tx_event_args()
    args["event_type"] = "tx.user_intent.set"
    args["payload"] = {}
    with pytest.raises(ValueError, match="payload.user_intent is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_and_state_save_updates_last_applied_seq(
    state_store, repo_context
):
    state = _valid_tx_state()

    result = state_store.tx_event_append_and_state_save(
        **_base_tx_event_args(),
        state=state,
    )
    assert result["ok"] is True

    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["last_applied_seq"] == result["seq"]


def test_tx_state_save_sets_updated_at_when_missing(state_store, repo_context):
    state = _valid_tx_state()

    result = state_store.tx_state_save(state)
    assert result["ok"] is True

    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert isinstance(saved.get("updated_at"), str)
    assert saved["updated_at"]


def test_read_last_json_line_returns_last_valid(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(["", json.dumps({"seq": 1}), "   ", json.dumps({"seq": 2})]) + "\n",
        encoding="utf-8",
    )

    assert state_store.read_last_json_line(repo_context.tx_event_log) == {"seq": 2}


def test_read_json_file_valid_returns_dict(state_store, repo_context):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(json.dumps({"ok": True}), encoding="utf-8")

    assert state_store.read_json_file(repo_context.tx_state) == {"ok": True}


def test_next_tx_event_seq_missing_log_returns_one(state_store, repo_context):
    assert state_store.next_tx_event_seq() == 1


def test_read_last_json_line_all_blank_returns_none(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("\n\n   \n", encoding="utf-8")

    assert state_store.read_last_json_line(repo_context.tx_event_log) is None


def test_tx_event_append_rejects_blank_payload_string(state_store):
    args = _base_tx_event_args()
    args["payload"] = {"ticket_id": " "}
    with pytest.raises(ValueError, match="payload.ticket_id is required"):
        state_store.tx_event_append(**args)


def test_tx_event_append_allows_tx_begin_when_event_log_empty(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    result = state_store.tx_event_append(**_base_tx_event_args())
    assert result["ok"] is True


def test_tx_event_append_allows_verify_start_with_missing_file_intents_list(
    state_store, repo_context
):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = None
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(json.dumps(state), encoding="utf-8")

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.start"
    args["payload"] = {}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_file_intent_add_requires_matching_planned_step(state_store):
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


def test_tx_event_append_verify_pass_requires_running_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["verify_state"] = {"status": "not_started", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.pass"
    args["payload"] = {"ok": True}
    with pytest.raises(ValueError, match="verify result requires verify.start"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_done_requires_running_commit_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["commit_state"] = {"status": "not_started", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.done"
    args["payload"] = {"sha": "sha", "branch": "main", "diff_summary": "diff"}
    with pytest.raises(ValueError, match="commit result requires commit.start"):
        state_store.tx_event_append(**args)


def test_tx_event_append_commit_fail_allows_running_commit_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["commit_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.fail"
    args["payload"] = {"error": "boom"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_verify_fail_allows_running_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["verify_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.fail"
    args["payload"] = {"ok": False}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_file_intent_update_allows_non_str_current_state(state_store):
    state = _valid_tx_state()
    state["active_tx"]["file_intents"] = [
        {
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t1-s1",
            "state": None,
            "last_event_seq": 0,
        }
    ]
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.update"
    args["payload"] = {"path": "a.py", "state": "started"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_state_save_rejects_none_state(state_store):
    with pytest.raises(ValueError, match="state is required"):
        state_store.tx_state_save(None)


def test_validate_tx_state_requires_updated_at(state_store):
    state = _valid_tx_state()
    with pytest.raises(ValueError, match="updated_at is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_active_tx_dict(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["active_tx"] = None
    with pytest.raises(ValueError, match="active_tx is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_rejects_invalid_phase_value(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["active_tx"]["phase"] = "bogus"
    with pytest.raises(ValueError, match="active_tx.phase is invalid"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_verify_state_dict(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["active_tx"]["verify_state"] = None
    with pytest.raises(ValueError, match="active_tx.verify_state is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_commit_state_dict(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["active_tx"]["commit_state"] = None
    with pytest.raises(ValueError, match="active_tx.commit_state is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_integrity_dict(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["integrity"] = None
    with pytest.raises(ValueError, match="integrity is required"):
        state_store._validate_tx_state(state)


def test_validate_tx_state_requires_integrity_rebuilt_from_seq(state_store):
    state = _valid_tx_state()
    state["updated_at"] = "now"
    state["integrity"].pop("rebuilt_from_seq")
    with pytest.raises(ValueError, match="integrity.rebuilt_from_seq is required"):
        state_store._validate_tx_state(state)


def test_tx_event_append_allows_verify_pass_when_running(state_store):
    state = _valid_tx_state()
    state["active_tx"]["verify_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.verify.pass"
    args["payload"] = {"ok": True}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_allows_commit_done_when_running(state_store):
    state = _valid_tx_state()
    state["active_tx"]["commit_state"] = {"status": "running", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.commit.done"
    args["payload"] = {"sha": "sha", "branch": "main", "diff_summary": "diff"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_allows_file_intent_complete_when_verified_and_passed(
    state_store,
):
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
    state["active_tx"]["verify_state"] = {"status": "passed", "last_result": None}
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.file_intent.complete"
    args["payload"] = {"path": "a.py", "state": "verified"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_require_payload_str_allows_empty_when_flagged(state_store):
    payload = {"note": "   "}
    result = state_store._require_payload_str(payload, "note", allow_empty=True)
    assert result == "   "


def test_tx_event_append_allows_end_done_with_summary(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.end.done"
    args["payload"] = {"summary": "finished"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_tx_event_append_allows_end_blocked_with_reason(state_store):
    state = _valid_tx_state()
    state_store.tx_state_save(state)

    args = _base_tx_event_args()
    args["event_type"] = "tx.end.blocked"
    args["payload"] = {"reason": "waiting"}
    result = state_store.tx_event_append(**args)
    assert result["ok"] is True


def test_read_last_json_line_skips_trailing_blanks(state_store, repo_context):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join([json.dumps({"seq": 1}), "", "   "]) + "\n",
        encoding="utf-8",
    )

    assert state_store.read_last_json_line(repo_context.tx_event_log) == {"seq": 1}


def test_tx_event_append_allows_tx_begin_when_active_done(state_store):
    state = _valid_tx_state()
    state["active_tx"]["status"] = "done"
    state["active_tx"]["phase"] = "done"
    state_store.tx_state_save(state)

    result = state_store.tx_event_append(**_base_tx_event_args())
    assert result["ok"] is True
