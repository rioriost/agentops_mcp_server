import json

from agentops_mcp_server.tool_router import ToolRouter


def _build_registry(calls):
    def snapshot_load():
        calls["snapshot_load"] = True
        return {"ok": True}

    def echo(value=None):
        return {"value": value, "blob": "x" * 5000}

    return {
        "snapshot_load": {
            "description": "Load snapshot",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": snapshot_load,
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
    }


def test_tools_list_includes_workspace_root_and_truncate_limit(
    repo_context, state_store
):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)
    result = tool_router.tools_list()
    assert result["tools"]

    for tool in result["tools"]:
        input_schema = tool["inputSchema"]
        assert "workspace_root" in input_schema["properties"]
        assert "truncate_limit" in input_schema["properties"]


def test_tools_call_alias_and_workspace_root_restore(
    repo_context, state_store, tmp_path
):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)

    original_root = repo_context.get_repo_root()
    other_root = tmp_path / "other"
    other_root.mkdir()

    payload = tool_router.tools_call(
        "snapshot.load", {"workspace_root": str(other_root)}
    )
    content = json.loads(payload["content"][0]["text"])

    assert calls["snapshot_load"] is True
    assert content["ok"] is True
    assert repo_context.get_repo_root() == original_root


def test_tools_call_truncate_limit_summarizes(repo_context, state_store):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)

    payload = tool_router.tools_call("echo", {"value": "ok", "truncate_limit": 10})
    content = json.loads(payload["content"][0]["text"])

    assert content["truncated"] is True
    assert "summary" in content


def test_tools_call_missing_workspace_root_adds_warning(repo_context, state_store):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)

    payload = tool_router.tools_call("echo", {"value": "ok"})
    content = json.loads(payload["content"][0]["text"])

    warnings = content.get("warnings") or []
    assert any(warning.get("code") == "workspace_root.missing" for warning in warnings)
