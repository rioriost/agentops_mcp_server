import io
import json
import subprocess
import sys
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


def test_read_last_json_line_returns_none_on_invalid_json(temp_repo):
    journal = temp_repo / ".agent" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("not-json\n", encoding="utf-8")
    assert m._read_last_json_line(journal) is None


def test_next_journal_seq_defaults_to_one(temp_repo):
    assert m._next_journal_seq() == 1


def test_journal_append_writes_event(temp_repo):
    result = m.journal_append(
        kind="session.start",
        payload={"note": "hi"},
        session_id="s1",
        agent_id="a1",
    )
    assert result["ok"] is True
    assert result["seq"] == 1

    journal = temp_repo / ".agent" / "journal.jsonl"
    record = json.loads(journal.read_text(encoding="utf-8").strip())
    assert record["kind"] == "session.start"
    assert record["payload"]["note"] == "hi"
    assert record["session_id"] == "s1"
    assert record["agent_id"] == "a1"


def test_snapshot_load_missing_returns_reason(temp_repo):
    result = m.snapshot_load()
    assert result["ok"] is False
    assert result["reason"] == "snapshot not found"


def test_checkpoint_read_missing_returns_reason(temp_repo):
    result = m.checkpoint_read()
    assert result["ok"] is False
    assert result["reason"] == "checkpoint not found"


def test_checkpoint_update_requires_last_applied_seq(temp_repo):
    with pytest.raises(ValueError, match="last_applied_seq is required"):
        m.checkpoint_update(last_applied_seq=None)


def test_checkpoint_read_invalid_json_returns_not_found(temp_repo):
    checkpoint = temp_repo / ".agent" / "checkpoint.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text("{bad", encoding="utf-8")
    result = m.checkpoint_read()
    assert result["ok"] is False
    assert result["reason"] == "checkpoint not found"


def test_read_journal_events_filters_and_counts_invalid(temp_repo):
    journal = temp_repo / ".agent" / "journal.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "\n".join(
            [
                "{bad json}",
                json.dumps({"seq": "nope"}),
                json.dumps({"seq": 1, "kind": "skip"}),
                json.dumps({"seq": 2, "kind": "keep"}),
                json.dumps({"seq": 4, "kind": "too-high"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = m._read_journal_events(start_seq=1, end_seq=3)
    assert [event["seq"] for event in result["events"]] == [2]
    assert result["invalid_lines"] == 2
    assert result["last_seq"] == 2


def test_resolve_path_handles_default_and_relative(temp_repo, tmp_path):
    default = temp_repo / "default.txt"
    assert m._resolve_path(None, default) == default
    assert m._resolve_path("logs/out.txt", default) == temp_repo / "logs" / "out.txt"

    absolute = tmp_path / "abs.txt"
    assert m._resolve_path(str(absolute), default) == absolute


def test_write_text_creates_parent_dirs(temp_repo):
    target = temp_repo / "nested" / "file.txt"
    m._write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_read_json_file_invalid_returns_none(temp_repo):
    path = temp_repo / "bad.json"
    path.write_text("{bad", encoding="utf-8")
    assert m._read_json_file(path) is None


def test_sanitize_args_truncates_strings():
    long_text = "x" * 2100
    result = m._sanitize_args({"a": long_text, "b": 1})
    assert result["a"].endswith("...(truncated)")
    assert result["b"] == 1


def test_summarize_result_truncates_large_payload():
    result = m._summarize_result({"text": "x" * 2100}, limit=50)
    assert result["truncated"] is True
    assert "summary" in result


def test_unique_preserve_order_keeps_first_occurrence():
    assert m._unique_preserve_order(["a", "b", "a", "c"]) == ["a", "b", "c"]


def test_normalize_test_candidate_suffix_rules():
    assert m._normalize_test_candidate("tests/foo.py", ".py") == "tests/foo_test.py"
    assert m._normalize_test_candidate("src/foo.py", "") == "src/foo.py"


def test_test_candidates_for_non_code_returns_empty():
    assert m._test_candidates_for_path("README.md") == []


def test_truncate_text_behaviors():
    assert m._truncate_text(None) is None
    assert m._truncate_text("short", limit=10) == "short"
    result = m._truncate_text("hello world", limit=5)
    assert result.startswith("hello")
    assert result.endswith("...(truncated)")


def test_commit_message_from_status_counts():
    assert m._commit_message_from_status([]) == "chore: no-op"
    assert m._commit_message_from_status([" M a", " M b"]) == "chore: update 2 file(s)"


def test_git_status_porcelain_parses_lines(monkeypatch):
    monkeypatch.setattr(m, "git", lambda *args: " M a\n\n?? b\n")
    assert m._git_status_porcelain() == ["M a", "?? b"]


def test_tests_suggest_uses_git_diff_when_none(monkeypatch):
    def fake_git(*args):
        if args == ("diff", "--name-only"):
            return "src/agentops_mcp_server/main.py"
        if args == ("diff", "--name-only", "--cached"):
            return "tests/test_main.py"
        return ""

    monkeypatch.setattr(m, "git", fake_git)
    result = m.tests_suggest()
    paths = {item["path"] for item in result["suggestions"]}
    assert "tests/agentops_mcp_server/main_test.py" in paths
    assert "tests/test_main.py" in paths


def test_tests_suggest_adds_investigate_for_failures():
    result = m.tests_suggest(diff="", failures="boom")
    assert result["suggestions"] == [
        {"path": "(investigate)", "reason": "verify failures present"}
    ]


def test_tests_suggest_from_failures_requires_path():
    with pytest.raises(ValueError):
        m.tests_suggest_from_failures("")


def test_tests_suggest_from_failures_missing_file(temp_repo):
    with pytest.raises(FileNotFoundError):
        m.tests_suggest_from_failures("missing.log")


def test_tests_suggest_from_failures_relative_path(temp_repo, monkeypatch):
    log_path = temp_repo / "logs" / "fail.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("boom", encoding="utf-8")
    monkeypatch.setattr(m, "git", lambda *args: "")
    result = m.tests_suggest_from_failures("logs/fail.txt")
    assert result["suggestions"][0]["path"] == "(investigate)"


def test_session_capture_context_verify_unavailable(monkeypatch):
    monkeypatch.setattr(m, "git", lambda *args: "main")
    monkeypatch.setattr(m, "run_verify", "nope")
    context = m.session_capture_context(run_verify=True)
    assert context["verify"]["ok"] is False
    assert context["verify"]["error"] == "verify unavailable"


def test_session_capture_context_runs_verify(monkeypatch):
    monkeypatch.setattr(m, "git", lambda *args: "main")
    monkeypatch.setattr(m, "run_verify", lambda: {"ok": True})
    context = m.session_capture_context(run_verify=True)
    assert context["verify"]["ok"] is True


def test_read_journal_events_missing_file(temp_repo):
    result = m._read_journal_events(start_seq=0)
    assert result["events"] == []
    assert result["last_seq"] == 0


def test_journal_append_requires_kind(temp_repo):
    with pytest.raises(ValueError, match="kind is required"):
        m.journal_append(kind="", payload={})


def test_commit_if_verified_success(monkeypatch):
    monkeypatch.setattr(
        m, "run_verify", lambda **kwargs: {"ok": True, "returncode": 0, "stderr": ""}
    )
    monkeypatch.setattr(m, "_journal_safe", lambda *args, **kwargs: None)
    monkeypatch.setattr(m, "_git_diff_stat_cached", lambda: "diff")

    calls = {"git": []}

    def fake_git(*args):
        calls["git"].append(args)
        if args == ("rev-parse", "HEAD"):
            return "abc"
        return ""

    monkeypatch.setattr(m, "git", fake_git)
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: None)

    result = m.commit_if_verified("msg")
    assert result["sha"] == "abc"
    assert result["message"] == "msg"


def test_repo_commit_with_files_list(monkeypatch):
    monkeypatch.setattr(m, "_git_status_porcelain", lambda: [" M a", " M b"])
    monkeypatch.setattr(m, "_journal_safe", lambda *args, **kwargs: None)
    monkeypatch.setattr(m, "_git_diff_stat_cached", lambda: "diff")

    calls = {"git": []}

    def fake_git(*args):
        calls["git"].append(args)
        if args == ("rev-parse", "HEAD"):
            return "abc"
        return ""

    monkeypatch.setattr(m, "git", fake_git)
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: None)

    result = m.repo_commit(message="", files="a.txt, b.txt", run_verify=False)
    assert result["ok"] is True
    assert ("add", "a.txt", "b.txt") in calls["git"]
    assert result["message"].startswith("chore:")


def test_repo_commit_raises_on_verify_failure(monkeypatch):
    monkeypatch.setattr(
        m,
        "run_verify",
        lambda **kwargs: {"ok": False, "returncode": 1, "stderr": "nope", "stdout": ""},
    )
    with pytest.raises(RuntimeError, match="verify failed"):
        m.repo_commit(message="msg", run_verify=True)


def test_read_last_json_line_missing_file(temp_repo):
    missing = temp_repo / ".agent" / "missing.jsonl"
    assert m._read_last_json_line(missing) is None


def test_read_journal_events_invalid_bounds():
    with pytest.raises(ValueError, match="start_seq must be >= 0"):
        m._read_journal_events(start_seq=-1)

    with pytest.raises(ValueError, match="end_seq must be >= start_seq"):
        m._read_journal_events(start_seq=2, end_seq=1)


def test_repo_status_summary_uses_git(monkeypatch):
    outputs = {
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--short"): " M file.txt",
        ("diff", "--stat"): "file.txt | 1 +",
        ("diff", "--stat", "--cached"): "",
        ("log", "-1", "--oneline"): "abc123 test commit",
        ("diff", "--name-only"): "file.txt",
        ("diff", "--name-only", "--cached"): "",
    }

    def fake_git(*args):
        return outputs.get(args, "")

    monkeypatch.setattr(m, "git", fake_git)
    summary = m.repo_status_summary()
    assert summary["branch"] == "main"
    assert summary["status"] == " M file.txt"
    assert summary["diff"] == "file.txt | 1 +"
    assert summary["staged_diff"] == ""
    assert summary["last_commit"] == "abc123 test commit"
    assert summary["files"]["unstaged"] == "file.txt"
    assert summary["files"]["staged"] == ""


def test_repo_commit_message_suggest_diff_none_uses_git(monkeypatch):
    outputs = {
        ("diff", "--stat", "--cached"): "docs/readme.md | 1 +",
        ("diff", "--stat"): "",
        ("diff", "--name-only", "--cached"): "docs/readme.md",
        ("diff", "--name-only"): "",
    }

    def fake_git(*args):
        return outputs.get(args, "")

    monkeypatch.setattr(m, "git", fake_git)
    result = m.repo_commit_message_suggest(diff=None)
    assert result["files"] == ["docs/readme.md"]
    assert result["suggestions"][0].startswith("docs:")


def test_main_writes_error_response(monkeypatch):
    input_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "nope"}) + "\n"
    stdin = io.StringIO(input_req)
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(m, "_journal_safe", lambda *args, **kwargs: None)

    m.main()

    output = stdout.getvalue().strip()
    resp = json.loads(output)
    assert resp["id"] == 1
    assert resp["error"]["code"] == -32000
    assert "Unknown method" in resp["error"]["message"]


def test_auto_snapshot_checkpoint_missing_journal(temp_repo):
    result = m._auto_snapshot_checkpoint_after_commit()
    assert result["ok"] is False
    assert result["reason"] == "journal not found"


def test_auto_snapshot_checkpoint_no_events(temp_repo):
    m.JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    m.JOURNAL.write_text("", encoding="utf-8")
    result = m._auto_snapshot_checkpoint_after_commit()
    assert result["ok"] is False
    assert result["reason"] == "no journal events"
    assert result["last_seq"] == 0
