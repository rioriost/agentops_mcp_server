import pytest

from agentops_mcp_server import main as m

pytestmark = pytest.mark.release


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
