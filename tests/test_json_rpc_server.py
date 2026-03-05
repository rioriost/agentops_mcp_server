import json

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
