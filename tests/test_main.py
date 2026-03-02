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
