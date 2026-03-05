import io
import json
import sys

import pytest

from agentops_mcp_server.json_rpc_server import JsonRpcServer
from agentops_mcp_server.tool_router import ToolRouter


def _build_registry():
    def echo(value=None):
        return {"ok": True, "value": value}

    return {
        "echo": {
            "description": "Echo payload",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": echo,
        }
    }


def test_handle_request_initialize(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    resp = server.handle_request(req)

    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "agentops-server"


def test_handle_request_tools_list(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    resp = server.handle_request(req)

    assert resp["id"] == 2
    assert resp["result"]["tools"]


def test_handle_request_tools_call_invalid_arguments(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": []},
    }
    with pytest.raises(ValueError):
        server.handle_request(req)


def test_handle_request_tools_call_payload(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

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


def test_handle_request_shutdown_and_initialized(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    shutdown = {"jsonrpc": "2.0", "id": 5, "method": "shutdown"}
    initialized = {"jsonrpc": "2.0", "id": 6, "method": "initialized"}

    assert server.handle_request(shutdown)["result"] is None
    assert server.handle_request(initialized)["result"] is None


def test_handle_request_unknown_method_raises(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    req = {"jsonrpc": "2.0", "id": 7, "method": "nope"}
    with pytest.raises(ValueError, match="Unknown method"):
        server.handle_request(req)


def test_handle_request_returns_none_without_id(repo_context, state_store):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    req = {"jsonrpc": "2.0", "method": "tools/list"}
    assert server.handle_request(req) is None


def test_run_emits_responses(repo_context, state_store, monkeypatch):
    tool_router = ToolRouter(_build_registry(), repo_context, state_store)
    server = JsonRpcServer(tool_router, state_store)

    stdin = io.StringIO(
        "\n".join(
            [
                '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}',
                '{"jsonrpc": "2.0", "id": 2, "method": "nope"}',
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
