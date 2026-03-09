from agentops_mcp_server.tool_registry import build_tool_registry


def _dummy(**_kwargs):
    return {}


def test_build_tool_registry_includes_expected_keys():
    registry = build_tool_registry(
        workspace_initialize=_dummy,
        commit_if_verified=_dummy,
        tx_event_append=_dummy,
        tx_state_save=_dummy,
        tx_state_rebuild=_dummy,
        repo_verify=_dummy,
        repo_commit=_dummy,
        repo_status_summary=_dummy,
        repo_commit_message_suggest=_dummy,
        session_capture_context=_dummy,
        tests_suggest=_dummy,
        tests_suggest_from_failures=_dummy,
        ops_compact_context=_dummy,
        ops_handoff_export=_dummy,
        ops_resume_brief=_dummy,
        ops_start_task=_dummy,
        ops_update_task=_dummy,
        ops_end_task=_dummy,
        ops_add_file_intent=_dummy,
        ops_update_file_intent=_dummy,
        ops_complete_file_intent=_dummy,
        ops_capture_state=_dummy,
        ops_task_summary=_dummy,
        ops_observability_summary=_dummy,
    )

    expected_keys = {
        "workspace_initialize",
        "commit_if_verified",
        "tx_event_append",
        "tx_state_save",
        "tx_state_rebuild",
        "repo_verify",
        "repo_commit",
        "repo_status_summary",
        "repo_commit_message_suggest",
        "session_capture_context",
        "tests_suggest",
        "tests_suggest_from_failures",
        "ops_compact_context",
        "ops_handoff_export",
        "ops_resume_brief",
        "ops_start_task",
        "ops_update_task",
        "ops_end_task",
        "ops_add_file_intent",
        "ops_update_file_intent",
        "ops_complete_file_intent",
        "ops_capture_state",
        "ops_task_summary",
        "ops_observability_summary",
    }

    assert expected_keys.issubset(set(registry.keys()))


def test_registry_entries_include_schema_and_handler():
    registry = build_tool_registry(
        workspace_initialize=_dummy,
        commit_if_verified=_dummy,
        tx_event_append=_dummy,
        tx_state_save=_dummy,
        tx_state_rebuild=_dummy,
        repo_verify=_dummy,
        repo_commit=_dummy,
        repo_status_summary=_dummy,
        repo_commit_message_suggest=_dummy,
        session_capture_context=_dummy,
        tests_suggest=_dummy,
        tests_suggest_from_failures=_dummy,
        ops_compact_context=_dummy,
        ops_handoff_export=_dummy,
        ops_resume_brief=_dummy,
        ops_start_task=_dummy,
        ops_update_task=_dummy,
        ops_end_task=_dummy,
        ops_add_file_intent=_dummy,
        ops_update_file_intent=_dummy,
        ops_complete_file_intent=_dummy,
        ops_capture_state=_dummy,
        ops_task_summary=_dummy,
        ops_observability_summary=_dummy,
    )

    workspace_initialize = registry["workspace_initialize"]
    assert workspace_initialize["handler"] is _dummy
    assert workspace_initialize["input_schema"]["required"] == ["cwd"]
    assert workspace_initialize["input_schema"]["properties"]["cwd"]["type"] == "string"

    tx_event = registry["tx_event_append"]
    assert tx_event["handler"] is _dummy
    assert set(tx_event["input_schema"]["required"]) == {
        "tx_id",
        "ticket_id",
        "event_type",
        "phase",
        "step_id",
        "actor",
        "session_id",
        "payload",
    }

    commit = registry["commit_if_verified"]
    assert commit["handler"] is _dummy
    assert commit["input_schema"]["required"] == ["message"]

    ops_add_file_intent = registry["ops_add_file_intent"]
    assert ops_add_file_intent["handler"] is _dummy
    assert ops_add_file_intent["input_schema"]["required"] == [
        "path",
        "operation",
        "purpose",
    ]

    ops_update_file_intent = registry["ops_update_file_intent"]
    assert ops_update_file_intent["handler"] is _dummy
    assert ops_update_file_intent["input_schema"]["required"] == ["path", "state"]

    ops_complete_file_intent = registry["ops_complete_file_intent"]
    assert ops_complete_file_intent["handler"] is _dummy
    assert ops_complete_file_intent["input_schema"]["required"] == ["path"]

    ops_capture_state = registry["ops_capture_state"]
    assert ops_capture_state["handler"] is _dummy
    assert ops_capture_state["input_schema"]["required"] == []
