import io
import json
import sys

import pytest

from agentops_mcp_server.json_rpc_server import JsonRpcServer
from agentops_mcp_server.tool_router import ToolRouter


def _build_registry():
    def workspace_initialize(cwd):
        return {
            "ok": True,
            "repo_root": cwd,
            "initialized": True,
            "changed": True,
        }

    def echo(value=None):
        return {"ok": True, "value": value}

    def fail_tool(reason=None):
        raise RuntimeError(reason or "boom")

    return {
        "workspace_initialize": {
            "description": "Bind workspace root for this MCP server session",
            "input_schema": {
                "type": "object",
                "properties": {"cwd": {"type": "string"}},
                "required": ["cwd"],
            },
            "handler": workspace_initialize,
        },
        "echo": {
            "description": "Echo payload",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": echo,
        },
        "fail_tool": {
            "description": "Always fails",
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": fail_tool,
        },
    }


def _build_server(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    return JsonRpcServer(tool_router, state_store)


def test_handle_request_initialize(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    resp = server.handle_request(req)

    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "agentops-server"
    assert resp["result"]["serverInfo"]["version"] == "0.4.13"


def test_handle_request_tools_list(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = server.handle_request(req)

    assert resp["id"] == 2
    assert resp["result"]["tools"]


def test_handle_request_tools_call_invalid_arguments(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": []},
    }
    with pytest.raises(ValueError):
        server.handle_request(req)


def test_handle_request_tools_call_payload(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"value": "ok"}},
    }
    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result["ok"] is True
    assert result["value"] == "ok"


def test_handle_request_workspace_initialize_payload(tmp_path):
    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext()
    state_store = StateStore(repo_context)
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "workspace_initialize",
            "arguments": {"cwd": str(tmp_path)},
        },
    }
    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result["ok"] is True
    assert result["initialized"] is True
    assert result["repo_root"] == str(tmp_path)


def test_handle_request_shutdown_and_initialized(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    shutdown = {"jsonrpc": "2.0", "id": 6, "method": "shutdown"}
    initialized = {"jsonrpc": "2.0", "id": 7, "method": "initialized"}

    assert server.handle_request(shutdown)["result"] is None
    assert server.handle_request(initialized)["result"] is None


def test_handle_request_unknown_method_raises(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {"jsonrpc": "2.0", "id": 8, "method": "nope"}
    with pytest.raises(ValueError, match="Unknown method"):
        server.handle_request(req)


def test_handle_request_returns_none_without_id(repo_context, state_store):
    server = _build_server(repo_context, state_store)

    req = {"jsonrpc": "2.0", "method": "tools/list"}
    assert server.handle_request(req) is None


def test_handle_request_logs_failed_tool_execution(tmp_path):
    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "fail_tool", "arguments": {"reason": "bad input"}},
    }

    with pytest.raises(RuntimeError, match="bad input"):
        server.handle_request(req)

    assert repo_context.errors is not None
    lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "fail_tool"
    assert lines[0]["tool_input"] == {"reason": "bad input"}
    assert lines[0]["tool_output"]["error"] == "bad input"
    assert isinstance(lines[0]["ts"], str)
    assert lines[0]["ts"]


def test_handle_request_does_not_log_failed_tool_when_uninitialized(tmp_path):
    from pathlib import Path

    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext(Path("/"))
    state_store = StateStore(repo_context)
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "fail_tool", "arguments": {"reason": "bad input"}},
    }

    with pytest.raises(ValueError, match="project root is not initialized"):
        server.handle_request(req)

    assert repo_context.errors is None


def test_handle_request_preserves_original_tool_error_when_logging_fails(
    tmp_path, monkeypatch
):
    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    server = _build_server(repo_context, state_store)

    def boom(*_args, **_kwargs):
        raise RuntimeError("cannot write error log")

    monkeypatch.setattr(state_store, "log_tool_error", boom)

    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": "fail_tool", "arguments": {"reason": "original failure"}},
    }

    with pytest.raises(RuntimeError, match="original failure"):
        server.handle_request(req)


def test_run_emits_responses_and_logs_failed_tool(tmp_path, monkeypatch):
    from agentops_mcp_server.repo_context import RepoContext
    from agentops_mcp_server.state_store import StateStore

    repo_context = RepoContext(tmp_path)
    state_store = StateStore(repo_context)
    server = _build_server(repo_context, state_store)

    stdin = io.StringIO(
        "\n".join(
            [
                '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fail_tool", "arguments": {"reason": "run failure"}}}',
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    server.run()

    lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["id"] == 1
    assert "result" in first
    assert second["id"] == 2
    assert "error" in second
    assert second["error"]["message"] == "run failure"

    assert repo_context.errors is not None
    records = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["tool_name"] == "fail_tool"
    assert records[0]["tool_input"] == {"reason": "run failure"}
    assert records[0]["tool_output"]["error"] == "run failure"
