import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agentops_mcp_server import init as init_mod
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


def test_parse_iso_ts_handles_z_and_invalid():
    parsed = m._parse_iso_ts("2026-03-02T12:00:00Z")
    assert parsed == datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert m._parse_iso_ts("not-a-ts") is None


def test_rotate_journal_if_prev_week_archives_last_week(temp_repo, monkeypatch):
    agent_dir = temp_repo / ".agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    journal = agent_dir / "journal.jsonl"

    last_week_event = {"ts": "2026-03-04T10:00:00+00:00", "seq": 1}
    current_week_event = {"ts": "2026-03-09T01:00:00+00:00", "seq": 2}
    invalid_json = "{bad json\n"
    invalid_ts = json.dumps({"ts": "not-a-ts", "seq": 3}) + "\n"

    journal.write_text(
        "".join(
            [
                json.dumps(last_week_event) + "\n",
                json.dumps(current_week_event) + "\n",
                invalid_json,
                invalid_ts,
            ]
        ),
        encoding="utf-8",
    )

    fixed_now = datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(m, "datetime", FixedDateTime)

    result = m._rotate_journal_if_prev_week()

    assert result["ok"] is True
    assert result["rotated"] is True
    assert result["archived"] == 1
    assert result["kept"] == 3

    archive = agent_dir / "journal.20260302-20260308.jsonl"
    assert archive.exists()

    archive_lines = archive.read_text(encoding="utf-8").splitlines()
    journal_lines = journal.read_text(encoding="utf-8").splitlines()

    assert archive_lines == [json.dumps(last_week_event)]
    assert json.dumps(current_week_event) in journal_lines
    assert "{bad json" in journal_lines
    assert json.dumps({"ts": "not-a-ts", "seq": 3}) in journal_lines
    assert json.dumps(last_week_event) not in journal_lines


def test_init_script_path_uses_package_resources(monkeypatch, tmp_path):
    script = tmp_path / "zed-agentops-init.sh"

    class DummyFiles:
        def __init__(self, base):
            self._base = base

        def joinpath(self, name):
            return self._base / name

    monkeypatch.setattr(init_mod.resources, "files", lambda _: DummyFiles(tmp_path))
    assert init_mod._script_path() == str(script)


def test_init_script_path_raises_when_resources_missing(monkeypatch):
    def boom(_):
        raise Exception("nope")

    monkeypatch.setattr(init_mod.resources, "files", boom)
    with pytest.raises(RuntimeError, match="zed-agentops-init.sh is not packaged"):
        init_mod._script_path()


def test_init_main_raises_when_script_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(init_mod, "_script_path", lambda: str(tmp_path / "missing.sh"))
    with pytest.raises(FileNotFoundError):
        init_mod.main()


def test_init_main_execv(monkeypatch, tmp_path):
    script = tmp_path / "zed-agentops-init.sh"
    script.write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    monkeypatch.setattr(init_mod, "_script_path", lambda: str(script))

    called = {}

    def fake_execv(path, args):
        called["path"] = path
        called["args"] = args

    monkeypatch.setattr(init_mod.os, "execv", fake_execv)
    monkeypatch.setattr(init_mod.sys, "argv", ["init.py", "--flag"])

    init_mod.main()

    assert called["path"] == "/usr/bin/env"
    assert called["args"] == ["env", "bash", str(script), "--flag"]


def test_run_verify_timeout_returns_error(temp_repo, monkeypatch):
    verify_path = temp_repo / ".zed" / "scripts" / "verify"
    verify_path.parent.mkdir(parents=True, exist_ok=True)
    verify_path.write_text("#!/bin/sh\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=[str(verify_path)], timeout=3, output="out")

    monkeypatch.setattr(m.subprocess, "run", boom)
    result = m.run_verify(timeout_sec=3)
    assert result["ok"] is False
    assert result["stdout"] == "out"
    assert "timed out after 3s" in result["stderr"]


def test_run_verify_success(temp_repo, monkeypatch):
    verify_path = temp_repo / ".zed" / "scripts" / "verify"
    verify_path.parent.mkdir(parents=True, exist_ok=True)
    verify_path.write_text("#!/bin/sh\n", encoding="utf-8")

    fake = SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: fake)
    result = m.run_verify(timeout_sec=5)
    assert result["ok"] is True
    assert result["stdout"] == "ok"


def test_git_error_message_includes_output(monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "status"], output=b"nope")

    monkeypatch.setattr(m.subprocess, "check_output", boom)
    with pytest.raises(RuntimeError, match="nope"):
        m.git("status")


def test_repo_commit_no_changes(temp_repo, monkeypatch):
    monkeypatch.setattr(m, "_git_status_porcelain", lambda: [])
    monkeypatch.setattr(m, "_journal_safe", lambda *args, **kwargs: None)
    result = m.repo_commit(message="msg", files="auto", run_verify=False)
    assert result["ok"] is False
    assert result["reason"] == "no changes to commit"


def test_repo_commit_no_files_specified(temp_repo, monkeypatch):
    monkeypatch.setattr(m, "_git_status_porcelain", lambda: [" M foo.py"])
    monkeypatch.setattr(m, "_journal_safe", lambda *args, **kwargs: None)
    result = m.repo_commit(message="msg", files=" , ", run_verify=False)
    assert result["ok"] is False
    assert result["reason"] == "no files specified"


def test_commit_if_verified_raises_on_failed_verify(monkeypatch):
    monkeypatch.setattr(
        m,
        "run_verify",
        lambda **kwargs: {"ok": False, "returncode": 2, "stderr": "nope"},
    )
    with pytest.raises(RuntimeError, match="verify failed"):
        m.commit_if_verified("msg")


@pytest.mark.parametrize(
    ("diff", "prefix"),
    [
        ("README.md\n", "docs"),
        ("tests/data.json\n", "test"),
        ("pyproject.toml\n", "chore"),
        ("src/agentops_mcp_server/main.py\n", "feat"),
    ],
)
def test_repo_commit_message_suggest_prefixes(diff, prefix):
    result = m.repo_commit_message_suggest(diff=diff)
    assert result["suggestions"][0].startswith(f"{prefix}:")


def test_tools_list_includes_workspace_root_for_all_tools():
    result = m.tools_list()
    for tool in result["tools"]:
        properties = tool["inputSchema"]["properties"]
        assert "workspace_root" in properties


def test_handle_request_initialize_response():
    resp = m.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["result"]["protocolVersion"] == "2024-11-05"


def test_handle_request_initialized_with_id_returns_none():
    resp = m.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialized"})
    assert resp["result"] is None


def test_handle_request_shutdown_with_id_returns_none():
    resp = m.handle_request({"jsonrpc": "2.0", "id": 1, "method": "shutdown"})
    assert resp["result"] is None


def test_handle_request_exit_raises():
    with pytest.raises(SystemExit):
        m.handle_request({"jsonrpc": "2.0", "id": 1, "method": "exit"})


def test_handle_request_unknown_method_raises():
    with pytest.raises(ValueError):
        m.handle_request({"jsonrpc": "2.0", "id": 1, "method": "nope"})


def test_tools_call_propagates_handler_error():
    with pytest.raises(ValueError):
        m.tools_call("snapshot_save", {"state": None})


def test_run_verify_missing_script_raises(temp_repo):
    with pytest.raises(FileNotFoundError):
        m.run_verify()


def test_git_missing_binary_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("no git")

    monkeypatch.setattr(m.subprocess, "check_output", boom)
    with pytest.raises(RuntimeError, match="git is not installed"):
        m.git("status")
