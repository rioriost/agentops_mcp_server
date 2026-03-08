import json

import pytest

from agentops_mcp_server.tool_router import ToolRouter


def _build_registry(calls):
    def workspace_initialize(cwd):
        calls["workspace_initialize"] = cwd
        return {
            "ok": True,
            "repo_root": cwd,
            "initialized": True,
            "changed": True,
        }

    def ops_compact_context(max_chars=None, include_diff=None):
        calls["ops_compact_context"] = (max_chars, include_diff)
        return {"ok": True}

    def echo(value=None):
        return {"value": value, "blob": "x" * 5000}

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
        "ops_compact_context": {
            "description": "Generate compact context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "max_chars": {"type": ["integer", "null"]},
                    "include_diff": {"type": ["boolean", "null"]},
                },
                "required": [],
            },
            "handler": ops_compact_context,
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
        "tests_suggest": {
            "description": "Suggest tests",
            "input_schema": {
                "type": "object",
                "properties": {
                    "diff": {"type": ["string", "null"]},
                    "failures": {"type": ["string", "null"]},
                },
                "required": [],
            },
            "handler": lambda diff=None, failures=None: {
                "diff": diff,
                "failures": failures,
            },
        },
    }


def test_tools_list_includes_truncate_limit(repo_context, state_store):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)
    result = tool_router.tools_list()
    assert result["tools"]

    for tool in result["tools"]:
        input_schema = tool["inputSchema"]
        assert "truncate_limit" in input_schema["properties"]


def test_tools_call_workspace_initialize_allowed_when_uninitialized(
    tmp_path, state_store
):
    uninitialized_context = state_store.repo_context.__class__(tmp_path.parent / "/")
    tool_router = ToolRouter(
        _build_registry({}),
        uninitialized_context,
        state_store.__class__(uninitialized_context),
    )

    payload = tool_router.tools_call(
        "workspace_initialize", {"cwd": str(tmp_path), "truncate_limit": 10}
    )
    content = json.loads(payload["content"][0]["text"])

    assert content["truncated"] is True
    assert "summary" in content


def test_tools_call_workspace_initialize_alias_works_when_uninitialized(
    tmp_path, state_store
):
    calls = {}
    uninitialized_context = state_store.repo_context.__class__(tmp_path.parent / "/")
    tool_router = ToolRouter(
        _build_registry(calls),
        uninitialized_context,
        state_store.__class__(uninitialized_context),
    )

    payload = tool_router.tools_call("workspace.initialize", {"cwd": str(tmp_path)})
    content = json.loads(payload["content"][0]["text"])

    assert calls["workspace_initialize"] == str(tmp_path)
    assert content["ok"] is True


def test_tools_call_alias_works_when_initialized(repo_context, state_store):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)

    payload = tool_router.tools_call("ops.compact_context", {})
    content = json.loads(payload["content"][0]["text"])

    assert calls["ops_compact_context"] == (None, None)
    assert content["ok"] is True


def test_tools_call_truncate_limit_summarizes(repo_context, state_store):
    calls = {}
    tool_router = ToolRouter(_build_registry(calls), repo_context, state_store)

    payload = tool_router.tools_call("echo", {"value": "ok", "truncate_limit": 10})
    content = json.loads(payload["content"][0]["text"])

    assert content["truncated"] is True
    assert "summary" in content


def test_tools_call_unknown_tool_raises(repo_context, state_store):
    tool_router = ToolRouter(_build_registry({}), repo_context, state_store)

    with pytest.raises(ValueError, match="Unknown tool"):
        tool_router.tools_call("missing.tool", {})


def test_tools_call_missing_required_arguments(repo_context, state_store):
    registry = {
        "needs_value": {
            "description": "Needs value",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            "handler": lambda value: {"value": value},
        }
    }
    tool_router = ToolRouter(registry, repo_context, state_store)

    with pytest.raises(ValueError, match="Missing required argument"):
        tool_router.tools_call("needs_value", {})


def test_tools_call_missing_required_field_in_arguments(repo_context, state_store):
    registry = {
        "needs_value": {
            "description": "Needs value",
            "input_schema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            "handler": lambda value: {"value": value},
        }
    }
    tool_router = ToolRouter(registry, repo_context, state_store)

    with pytest.raises(ValueError, match="Missing required argument"):
        tool_router.tools_call("needs_value", {"value": None})


def test_tools_call_non_dict_result(repo_context, state_store):
    registry = {
        "list_result": {
            "description": "List result",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": lambda: ["ok"],
        }
    }
    tool_router = ToolRouter(registry, repo_context, state_store)

    payload = tool_router.tools_call("list_result", {})
    content = json.loads(payload["content"][0]["text"])

    assert content["result"] == ["ok"]


def test_tools_call_blocks_file_backed_tool_when_uninitialized(tmp_path, state_store):
    calls = {}
    uninitialized_context = state_store.repo_context.__class__(tmp_path.parent / "/")
    tool_router = ToolRouter(
        _build_registry(calls),
        uninitialized_context,
        state_store.__class__(uninitialized_context),
    )

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        tool_router.tools_call("ops_compact_context", {})


def test_tools_call_allows_tests_suggest_when_uninitialized(tmp_path, state_store):
    uninitialized_context = state_store.repo_context.__class__(tmp_path.parent / "/")
    tool_router = ToolRouter(
        _build_registry({}),
        uninitialized_context,
        state_store.__class__(uninitialized_context),
    )

    payload = tool_router.tools_call(
        "tests_suggest", {"diff": "a.py", "failures": "boom"}
    )
    content = json.loads(payload["content"][0]["text"])

    assert content["diff"] == "a.py"
    assert content["failures"] == "boom"
