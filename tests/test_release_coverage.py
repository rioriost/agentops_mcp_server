import json

import pytest

from agentops_mcp_server import main as m

pytestmark = pytest.mark.release


@pytest.fixture
def temp_repo(tmp_path):
    original_root = m.REPO_ROOT
    m._set_repo_root(tmp_path)
    try:
        yield tmp_path
    finally:
        m._set_repo_root(original_root)


def test_parse_changed_files_from_diff_blocks():
    diff = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "diff --git a/docs/readme.md b/docs/readme.md\n"
    )
    assert m._parse_changed_files(diff) == ["src/foo.py", "docs/readme.md"]


def test_parse_changed_files_from_name_list():
    diff = "alpha.txt\nbeta/gamma.md\n"
    assert m._parse_changed_files(diff) == ["alpha.txt", "beta/gamma.md"]


def test_test_candidates_for_path_in_src():
    candidates = m._test_candidates_for_path("src/agentops_mcp_server/main.py")
    assert "src/agentops_mcp_server/main_test.py" in candidates
    assert "src/agentops_mcp_server/test_main.py" in candidates
    assert "tests/agentops_mcp_server/main_test.py" in candidates


def test_replay_events_to_state_updates_verify_status():
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
            "kind": "verify.start",
            "session_id": "s1",
            "payload": {"command": "verify"},
        },
        {
            "seq": 3,
            "event_id": "evt-3",
            "kind": "verify.end",
            "session_id": "s1",
            "payload": {"ok": True},
        },
    ]
    state = m.replay_events_to_state(snapshot_state={}, events=events)
    assert state["session_id"] == "s1"
    assert state["verification_status"] == "passed"
    assert state["last_action"] == "verify finished"


def test_init_replay_state_defaults():
    state = m._init_replay_state(None)
    assert state["session_id"] == ""
    assert state["replay_warnings"]["invalid_lines"] == 0
    assert state["replay_warnings"]["dropped_events"] == 0
    assert state["applied_event_ids"] == []


def test_append_applied_event_id_trims_oldest():
    state = {"applied_event_ids": ["evt-1", "evt-2"]}
    m._append_applied_event_id(state, "evt-3", max_size=2)
    assert state["applied_event_ids"] == ["evt-2", "evt-3"]


def test_select_target_session_id_prefers_latest_session_start():
    events = [
        {"seq": 1, "session_id": "s1", "kind": "task.start"},
        {"seq": 2, "session_id": "s2", "kind": "session.start"},
        {"seq": 3, "session_id": "s1", "kind": "session.start"},
    ]
    assert m._select_target_session_id(events, None) == "s1"


def test_select_target_session_id_prefers_explicit():
    events = [
        {"seq": 1, "session_id": "s1", "kind": "session.start"},
        {"seq": 2, "session_id": "s2", "kind": "session.start"},
    ]
    assert m._select_target_session_id(events, "s2") == "s2"


def test_apply_event_to_state_task_branches():
    state = {}
    m._apply_event_to_state(
        state, {"kind": "task.start", "payload": {"title": "Do work"}}
    )
    assert state["current_task"] == "Do work"
    assert state["current_phase"] == "task"
    assert state["last_action"] == "task started"

    m._apply_event_to_state(
        state,
        {"kind": "task.update", "payload": {"status": "review", "note": "progress"}},
    )
    assert state["current_phase"] == "review"
    assert state["last_action"] == "progress"

    m._apply_event_to_state(
        state,
        {"kind": "task.end", "payload": {"summary": "done", "next_action": "next"}},
    )
    assert state["current_task"] == ""
    assert state["last_action"] == "done"
    assert state["next_step"] == "next"


def test_apply_event_to_state_commit_and_error_branches():
    state = {}
    m._apply_event_to_state(
        state, {"kind": "commit.start", "payload": {"message": "msg"}}
    )
    assert state["last_commit"] == "msg"
    assert state["last_action"] == "commit started"

    m._apply_event_to_state(
        state, {"kind": "commit.end", "payload": {"sha": "abc", "summary": "sum"}}
    )
    assert state["last_commit"] == "abc"
    assert state["last_action"] == "commit finished"

    m._apply_event_to_state(
        state, {"kind": "tool.result", "payload": {"ok": False, "error": "boom"}}
    )
    assert state["last_error"] == "boom"

    m._apply_event_to_state(state, {"kind": "error", "payload": {"message": "bad"}})
    assert state["last_error"] == "bad"
    assert state["last_action"] == "error recorded"


def test_tests_suggest_for_src_path():
    diff = "src/agentops_mcp_server/main.py\n"
    result = m.tests_suggest(diff=diff)
    paths = {item["path"] for item in result["suggestions"]}
    assert "tests/agentops_mcp_server/main_test.py" in paths


def test_tests_suggest_for_test_path():
    diff = "tests/test_main.py\n"
    result = m.tests_suggest(diff=diff)
    assert result["suggestions"] == [
        {"path": "tests/test_main.py", "reason": "existing test changed"}
    ]


def test_tests_suggest_for_non_code():
    diff = "README.md\n"
    result = m.tests_suggest(diff=diff)
    assert result["suggestions"] == [
        {"path": "(none)", "reason": "no obvious test targets"}
    ]


def test_roll_forward_replay_uses_checkpoint_seq(temp_repo):
    m.snapshot_save(state={}, session_id="s1", last_applied_seq=5)
    m.journal_append(
        kind="session.start", payload={}, session_id="s1", event_id="evt-1"
    )
    m.journal_append(kind="task.start", payload={}, session_id="s1", event_id="evt-2")
    m.journal_append(kind="task.end", payload={}, session_id="s1", event_id="evt-3")
    m.checkpoint_update(last_applied_seq=2, snapshot_path=m.SNAPSHOT.name)

    replay = m.roll_forward_replay()
    assert replay["start_seq"] == 2
    assert [event["seq"] for event in replay["events"]] == [3]


def test_roll_forward_replay_uses_snapshot_seq_when_checkpoint_missing_seq(temp_repo):
    m.snapshot_save(state={}, session_id="s1", last_applied_seq=2)
    m.journal_append(
        kind="session.start", payload={}, session_id="s1", event_id="evt-1"
    )
    m.journal_append(kind="task.start", payload={}, session_id="s1", event_id="evt-2")
    m.journal_append(kind="task.end", payload={}, session_id="s1", event_id="evt-3")

    checkpoint_path = temp_repo / ".agent" / "checkpoint-custom.json"
    checkpoint_path.write_text(
        json.dumps(
            {
                "checkpoint_id": "c1",
                "ts": m._now_iso(),
                "project_root": str(m.REPO_ROOT),
                "snapshot_path": m.SNAPSHOT.name,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    replay = m.roll_forward_replay(checkpoint_path=str(checkpoint_path))
    assert replay["start_seq"] == 2
    assert [event["seq"] for event in replay["events"]] == [3]


def test_roll_forward_replay_end_seq_filters(temp_repo):
    m.snapshot_save(state={}, session_id="s1", last_applied_seq=0)
    m.journal_append(
        kind="session.start", payload={}, session_id="s1", event_id="evt-1"
    )
    m.journal_append(kind="task.start", payload={}, session_id="s1", event_id="evt-2")
    m.journal_append(kind="task.end", payload={}, session_id="s1", event_id="evt-3")
    m.journal_append(kind="task.end", payload={}, session_id="s1", event_id="evt-4")
    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)

    replay = m.roll_forward_replay(start_seq=0, end_seq=2)
    assert [event["seq"] for event in replay["events"]] == [1, 2]
    assert replay["last_seq"] == 2


def test_tools_call_unknown_tool_raises(temp_repo):
    with pytest.raises(ValueError):
        m.tools_call("unknown.tool", {})


def test_tools_call_alias_maps_to_handler(temp_repo):
    payload = m.tools_call("repo.commit_message_suggest", {"diff": ""})
    content = payload["content"][0]["text"]
    result = json.loads(content)
    assert result["diff"] == ""
    assert result["files"] == []
    assert result["suggestions"]
