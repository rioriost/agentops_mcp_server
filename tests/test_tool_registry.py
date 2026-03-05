from agentops_mcp_server.tool_registry import build_tool_registry


def _dummy(**_kwargs):
    return {}


def test_build_tool_registry_includes_expected_keys():
    registry = build_tool_registry(
        commit_if_verified=_dummy,
        journal_append=_dummy,
        snapshot_save=_dummy,
        snapshot_load=_dummy,
        checkpoint_update=_dummy,
        checkpoint_read=_dummy,
        roll_forward_replay=_dummy,
        continue_state_rebuild=_dummy,
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
        ops_capture_state=_dummy,
        ops_task_summary=_dummy,
        ops_observability_summary=_dummy,
    )

    expected_keys = {
        "commit_if_verified",
        "journal_append",
        "snapshot_save",
        "snapshot_load",
        "checkpoint_update",
        "checkpoint_read",
        "roll_forward_replay",
        "continue_state_rebuild",
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
        "ops_capture_state",
        "ops_task_summary",
        "ops_observability_summary",
    }

    assert expected_keys.issubset(set(registry.keys()))


def test_registry_entries_include_schema_and_handler():
    registry = build_tool_registry(
        commit_if_verified=_dummy,
        journal_append=_dummy,
        snapshot_save=_dummy,
        snapshot_load=_dummy,
        checkpoint_update=_dummy,
        checkpoint_read=_dummy,
        roll_forward_replay=_dummy,
        continue_state_rebuild=_dummy,
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
        ops_capture_state=_dummy,
        ops_task_summary=_dummy,
        ops_observability_summary=_dummy,
    )

    journal = registry["journal_append"]
    assert journal["handler"] is _dummy
    assert journal["input_schema"]["required"] == ["kind", "payload"]

    commit = registry["commit_if_verified"]
    assert commit["handler"] is _dummy
    assert commit["input_schema"]["required"] == ["message"]
