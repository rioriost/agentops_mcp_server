import io
import json
import sys

import pytest

from agentops_mcp_server import json_rpc_server as json_rpc_mod
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

    def structured_fail_tool(reason=None):
        raise RuntimeError(
            {
                "ok": False,
                "error_code": "resume_required",
                "reason": reason or "resume exact active transaction",
                "recommended_next_tool": "ops_update_task",
                "recommended_action": "Resume the exact active transaction before switching work.",
            }
        )

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
        "structured_fail_tool": {
            "description": "Fails with structured payload",
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": structured_fail_tool,
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

    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result["ok"] is False
    assert result["reason"] == "bad input"

    assert repo_context.errors is not None
    lines = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["tool_name"] == "fail_tool"
    assert lines[0]["tool_input"] == {"reason": "bad input"}
    assert lines[0]["tool_output"]["reason"] == "bad input"
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

    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result["ok"] is False
    assert "project root is not initialized" in result["reason"]

    assert repo_context.errors is None


def test_write_json_writes_and_flushes(monkeypatch):
    written = []

    class DummyStdout:
        def write(self, text):
            written.append(("write", text))

        def flush(self):
            written.append(("flush", None))

    monkeypatch.setattr(sys, "stdout", DummyStdout())

    json_rpc_mod._write_json({"ok": True, "message": "hello"})

    assert written == [("write", '{"ok": true, "message": "hello"}\n'), ("flush", None)]


def test_handle_request_tools_call_defaults_missing_arguments(
    repo_context, state_store
):
    server = _build_server(repo_context, state_store)

    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": "echo"},
    }
    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result == {"ok": True, "value": None}


def test_handle_request_exit_calls_sys_exit(repo_context, state_store, monkeypatch):
    server = _build_server(repo_context, state_store)
    seen = {}

    def fake_exit(code):
        seen["code"] = code
        raise SystemExit(code)

    monkeypatch.setattr(sys, "exit", fake_exit)

    req = {"jsonrpc": "2.0", "id": 12, "method": "exit"}

    with pytest.raises(SystemExit) as excinfo:
        server.handle_request(req)

    assert excinfo.value.code == 0
    assert seen["code"] == 0


def test_run_ignores_blank_lines_and_writes_success_response(
    repo_context, state_store, monkeypatch
):
    server = _build_server(repo_context, state_store)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('\n  \n{"jsonrpc":"2.0","id":13,"method":"tools/list"}\n'),
    )

    written = []

    def fake_write_json(obj):
        written.append(obj)

    monkeypatch.setattr(json_rpc_mod, "_write_json", fake_write_json)

    server.run()

    assert written == [
        {
            "jsonrpc": "2.0",
            "id": 13,
            "result": server.tool_router.tools_list(),
        }
    ]


def test_run_writes_error_response_with_request_id(
    repo_context, state_store, monkeypatch
):
    server = _build_server(repo_context, state_store)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"jsonrpc":"2.0","id":14,"method":"nope"}\n'),
    )

    written = []

    def fake_write_json(obj):
        written.append(obj)

    monkeypatch.setattr(json_rpc_mod, "_write_json", fake_write_json)

    server.run()

    assert written == [
        {
            "jsonrpc": "2.0",
            "id": 14,
            "error": {"code": -32602, "message": "Unknown method: nope"},
        }
    ]


def test_run_writes_structured_error_data_when_exception_payload_is_structured(
    repo_context, state_store, monkeypatch
):
    server = _build_server(repo_context, state_store)

    def structured_boom(_req):
        raise RuntimeError(
            {
                "ok": False,
                "error_code": "resume_required",
                "reason": "resume exact active transaction",
                "recommended_next_tool": "ops_update_task",
            }
        )

    monkeypatch.setattr(server, "handle_request", structured_boom)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO('{"jsonrpc":"2.0","id":15,"method":"tools/list"}\n'),
    )

    written = []

    def fake_write_json(obj):
        written.append(obj)

    monkeypatch.setattr(json_rpc_mod, "_write_json", fake_write_json)

    server.run()

    assert written == [
        {
            "jsonrpc": "2.0",
            "id": 15,
            "error": {
                "code": -32000,
                "message": "resume exact active transaction",
                "data": {
                    "ok": False,
                    "error_code": "resume_required",
                    "reason": "resume exact active transaction",
                    "recommended_next_tool": "ops_update_task",
                },
            },
        }
    ]


def test_run_skips_error_response_without_request_id(
    repo_context, state_store, monkeypatch
):
    server = _build_server(repo_context, state_store)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"jsonrpc":"2.0","method":"nope"}\n')
    )

    written = []

    def fake_write_json(obj):
        written.append(obj)

    monkeypatch.setattr(json_rpc_mod, "_write_json", fake_write_json)

    server.run()

    assert written == []


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

    resp = server.handle_request(req)

    payload = resp["result"]["content"][0]["text"]
    result = json.loads(payload)
    assert result["ok"] is False
    assert result["reason"] == "original failure"


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
    assert "result" in second

    tool_result = json.loads(second["result"]["content"][0]["text"])
    assert tool_result["ok"] is False
    assert tool_result["reason"] == "run failure"

    assert repo_context.errors is not None
    records = [
        json.loads(line)
        for line in repo_context.errors.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["tool_name"] == "fail_tool"
    assert records[0]["tool_input"] == {"reason": "run failure"}
    assert records[0]["tool_output"]["reason"] == "run failure"
