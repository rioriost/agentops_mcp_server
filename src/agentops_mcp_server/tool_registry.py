from __future__ import annotations

from typing import Any, Callable, Dict


def build_tool_registry(
    *,
    workspace_initialize: Callable[..., Any],
    commit_if_verified: Callable[..., Any],
    tx_event_append: Callable[..., Any],
    tx_state_save: Callable[..., Any],
    tx_state_rebuild: Callable[..., Any],
    repo_verify: Callable[..., Any],
    repo_commit: Callable[..., Any],
    repo_status_summary: Callable[..., Any],
    repo_commit_message_suggest: Callable[..., Any],
    session_capture_context: Callable[..., Any],
    tests_suggest: Callable[..., Any],
    tests_suggest_from_failures: Callable[..., Any],
    ops_compact_context: Callable[..., Any],
    ops_handoff_export: Callable[..., Any],
    ops_resume_brief: Callable[..., Any],
    ops_start_task: Callable[..., Any],
    ops_update_task: Callable[..., Any],
    ops_end_task: Callable[..., Any],
    ops_add_file_intent: Callable[..., Any],
    ops_update_file_intent: Callable[..., Any],
    ops_complete_file_intent: Callable[..., Any],
    ops_capture_state: Callable[..., Any],
    ops_task_summary: Callable[..., Any],
    ops_observability_summary: Callable[..., Any],
) -> Dict[str, Any]:
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
        "commit_if_verified": {
            "description": "Verify then commit",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "timeout_sec": {"type": ["integer", "null"]},
                },
                "required": ["message"],
            },
            "handler": commit_if_verified,
        },
        "tx_event_append": {
            "description": "Append tx event",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tx_id": {"type": "string"},
                    "ticket_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "phase": {"type": "string"},
                    "step_id": {"type": "string"},
                    "actor": {"type": "object"},
                    "session_id": {"type": "string"},
                    "payload": {"type": "object"},
                    "event_id": {"type": ["string", "null"]},
                },
                "required": [
                    "tx_id",
                    "ticket_id",
                    "event_type",
                    "phase",
                    "step_id",
                    "actor",
                    "session_id",
                    "payload",
                ],
            },
            "handler": tx_event_append,
        },
        "tx_state_save": {
            "description": "Save transaction state",
            "input_schema": {
                "type": "object",
                "properties": {"state": {"type": "object"}},
                "required": ["state"],
            },
            "handler": tx_state_save,
        },
        "tx_state_rebuild": {
            "description": "Rebuild transaction state",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_seq": {"type": ["integer", "null"]},
                    "end_seq": {"type": ["integer", "null"]},
                    "tx_state_path": {"type": ["string", "null"]},
                    "event_log_path": {"type": ["string", "null"]},
                },
                "required": [],
            },
            "handler": tx_state_rebuild,
        },
        "repo_verify": {
            "description": "Run verify",
            "input_schema": {
                "type": "object",
                "properties": {"timeout_sec": {"type": ["integer", "null"]}},
                "required": [],
            },
            "handler": repo_verify,
        },
        "repo_commit": {
            "description": "Commit changes",
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {"type": ["string", "null"]},
                    "files": {"type": ["string", "null"]},
                    "run_verify": {"type": ["boolean", "null"]},
                    "timeout_sec": {"type": ["integer", "null"]},
                },
                "required": [],
            },
            "handler": repo_commit,
        },
        "repo_status_summary": {
            "description": "Repo status summary",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": repo_status_summary,
        },
        "repo_commit_message_suggest": {
            "description": "Suggest commit messages",
            "input_schema": {
                "type": "object",
                "properties": {"diff": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": repo_commit_message_suggest,
        },
        "session_capture_context": {
            "description": "Capture repo context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "run_verify": {"type": ["boolean", "null"]},
                    "log": {"type": ["boolean", "null"]},
                },
                "required": [],
            },
            "handler": session_capture_context,
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
            "handler": tests_suggest,
        },
        "tests_suggest_from_failures": {
            "description": "Suggest tests from failures",
            "input_schema": {
                "type": "object",
                "properties": {"log_path": {"type": "string"}},
                "required": ["log_path"],
            },
            "handler": tests_suggest_from_failures,
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
        "ops_handoff_export": {
            "description": "Export handoff JSON",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": ops_handoff_export,
        },
        "ops_resume_brief": {
            "description": "Generate a brief for resuming the exact active transaction using canonical next_action guidance",
            "input_schema": {
                "type": "object",
                "properties": {"max_chars": {"type": ["integer", "null"]}},
                "required": [],
            },
            "handler": ops_resume_brief,
        },
        "ops_start_task": {
            "description": "Record lifecycle start for the exact active transaction; does not bootstrap tx.begin",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                },
                "required": ["title"],
            },
            "handler": ops_start_task,
        },
        "ops_update_task": {
            "description": "Record lifecycle progress for the exact active transaction using canonical next_action ordering",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": ["string", "null"]},
                    "note": {"type": ["string", "null"]},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                    "user_intent": {"type": ["string", "null"]},
                },
                "required": [],
            },
            "handler": ops_update_task,
        },
        "ops_end_task": {
            "description": "Record terminal lifecycle outcome for the exact active transaction without resuming post-terminal work",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "next_action": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                },
                "required": ["summary"],
            },
            "handler": ops_end_task,
        },
        "ops_add_file_intent": {
            "description": "Register a file intent for the exact active transaction under canonical ordering",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "operation": {"type": "string"},
                    "purpose": {"type": "string"},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                },
                "required": ["path", "operation", "purpose"],
            },
            "handler": ops_add_file_intent,
        },
        "ops_update_file_intent": {
            "description": "Advance a file intent state for the exact active transaction under canonical ordering",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "state": {"type": "string"},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                },
                "required": ["path", "state"],
            },
            "handler": ops_update_file_intent,
        },
        "ops_complete_file_intent": {
            "description": "Complete a verified file intent for the exact active transaction after canonical verification",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                },
                "required": ["path"],
            },
            "handler": ops_complete_file_intent,
        },
        "ops_capture_state": {
            "description": "Capture canonical transaction state for exact-active-transaction resume",
            "input_schema": {
                "type": "object",
                "properties": {"session_id": {"type": ["string", "null"]}},
                "required": [],
            },
            "handler": ops_capture_state,
        },
        "ops_task_summary": {
            "description": "Summarize task state",
            "input_schema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": ["string", "null"]},
                    "max_chars": {"type": ["integer", "null"]},
                },
                "required": [],
            },
            "handler": ops_task_summary,
        },
        "ops_observability_summary": {
            "description": "Write observability summary",
            "input_schema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": ["string", "null"]},
                    "max_events": {"type": ["integer", "null"]},
                    "max_chars": {"type": ["integer", "null"]},
                },
                "required": [],
            },
            "handler": ops_observability_summary,
        },
    }
