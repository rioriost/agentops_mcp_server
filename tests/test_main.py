import io
import json
import sys

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


def test_tools_list_includes_workspace_root():
    result = m.tools_list()
    assert "tools" in result
    tools = result["tools"]
    assert tools
    input_schema = tools[0]["inputSchema"]
    assert "workspace_root" in input_schema["properties"]


def test_tools_call_alias_snapshot_load(temp_repo):
    payload = m.tools_call("snapshot.load", {})
    content = payload["content"][0]["text"]
    result = json.loads(content)
    assert result["ok"] is False
    assert result["reason"] == "snapshot not found"


def test_tools_call_workspace_root_restores_repo_root(tmp_path):
    original_root = m.REPO_ROOT
    payload = m.tools_call("snapshot_load", {"workspace_root": str(tmp_path)})
    content = payload["content"][0]["text"]
    result = json.loads(content)
    assert result["ok"] is False
    assert m.REPO_ROOT == original_root


def test_handle_request_tools_list():
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = m.handle_request(req)
    assert resp["id"] == 1
    assert "tools" in resp["result"]


def test_handle_request_tools_call_invalid_name_type():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": 123, "arguments": {}},
    }
    with pytest.raises(ValueError):
        m.handle_request(req)


def test_handle_request_tools_call_invalid_arguments_type():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "snapshot_load", "arguments": []},
    }
    with pytest.raises(ValueError):
        m.handle_request(req)


def test_repo_commit_message_suggest_empty_diff():
    result = m.repo_commit_message_suggest(diff="")
    assert result["diff"] == ""
    assert result["files"] == []
    assert result["suggestions"]


def test_main_emits_response(monkeypatch):
    input_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    stdin = io.StringIO(input_req)
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    m.main()

    output = stdout.getvalue().strip()
    resp = json.loads(output)
    assert resp["id"] == 1
    assert "result" in resp


def test_ops_compact_context_updates_state_and_journal(temp_repo):
    result = m.ops_compact_context(max_chars=80, include_diff=False)
    assert result["ok"] is True
    assert isinstance(result["compact_context"], str)

    loaded = m.snapshot_load()
    assert loaded["ok"] is True
    snapshot_state = loaded["snapshot"]["state"]
    assert snapshot_state["compact_context"] == result["compact_context"]

    journal_lines = m.JOURNAL.read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in journal_lines if line.strip()]
    assert "context.compact" in kinds


def test_ops_handoff_export_writes_json(temp_repo):
    result = m.ops_handoff_export(path=".agent/handoff.json")
    assert result["ok"] is True
    assert result["wrote"] is True
    assert result["path"]

    handoff_path = m.REPO_ROOT / ".agent" / "handoff.json"
    handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert "compact_context" in handoff_payload

    journal_lines = m.JOURNAL.read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in journal_lines if line.strip()]
    assert "session.handoff" in kinds


def test_ops_resume_brief_is_bounded(temp_repo):
    result = m.ops_resume_brief(max_chars=40)
    assert result["ok"] is True
    assert isinstance(result["brief"], str)
    assert len(result["brief"]) <= 40


def test_tools_call_truncate_limit_summarizes(temp_repo):
    payload = m.tools_call("snapshot_load", {"truncate_limit": 1})
    content = payload["content"][0]["text"]
    result = json.loads(content)
    assert result["truncated"] is True
    assert "summary" in result


def test_ops_task_lifecycle_records_events(temp_repo):
    start = m.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    update = m.ops_update_task(status="blocked", note="waiting", session_id="s1")
    end = m.ops_end_task(summary="done", next_action="next", session_id="s1")

    assert start["ok"] is True
    assert update["ok"] is True
    assert end["ok"] is True

    journal_lines = m.JOURNAL.read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in journal_lines if line.strip()]
    assert "task.start" in kinds
    assert "task.update" in kinds
    assert "task.end" in kinds


def test_ops_capture_state_updates_snapshot_and_checkpoint(temp_repo):
    m.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )
    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)
    m.journal_append(
        kind="session.start",
        payload={"note": "start"},
        session_id="s1",
    )

    result = m.ops_capture_state(session_id="s1")
    assert result["ok"] is True

    snapshot = m.snapshot_load()
    checkpoint = m.checkpoint_read()
    assert snapshot["ok"] is True
    assert checkpoint["ok"] is True

    journal_lines = m.JOURNAL.read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in journal_lines if line.strip()]
    assert "state.capture" in kinds


def test_ops_task_summary_emits_journal_and_text(temp_repo):
    m.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )
    m.journal_append(
        kind="task.start",
        payload={"title": "Build", "task_id": "t-1"},
        session_id="s1",
    )
    m.checkpoint_update(last_applied_seq=0, snapshot_path=m.SNAPSHOT.name)

    result = m.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_title"] == "Build"
    assert len(result["text"]) <= 40

    journal_lines = m.JOURNAL.read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in journal_lines if line.strip()]
    assert "task.summary" in kinds
