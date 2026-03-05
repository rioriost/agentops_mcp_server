from __future__ import annotations

from typing import Any, Callable, Dict


def build_tool_registry(
    *,
    commit_if_verified: Callable[..., Any],
    journal_append: Callable[..., Any],
    snapshot_save: Callable[..., Any],
    snapshot_load: Callable[..., Any],
    checkpoint_update: Callable[..., Any],
    checkpoint_read: Callable[..., Any],
    roll_forward_replay: Callable[..., Any],
    continue_state_rebuild: Callable[..., Any],
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
    ops_capture_state: Callable[..., Any],
    ops_task_summary: Callable[..., Any],
    ops_observability_summary: Callable[..., Any],
) -> Dict[str, Any]:
    return {
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
        "journal_append": {
            "description": "Append journal event",
            "input_schema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "payload": {"type": "object"},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                    "event_id": {"type": ["string", "null"]},
                },
                "required": ["kind", "payload"],
            },
            "handler": journal_append,
        },
        "snapshot_save": {
            "description": "Save snapshot",
            "input_schema": {
                "type": "object",
                "properties": {
                    "state": {"type": "object"},
                    "session_id": {"type": ["string", "null"]},
                    "last_applied_seq": {"type": ["integer", "null"]},
                    "snapshot_id": {"type": ["string", "null"]},
                },
                "required": ["state"],
            },
            "handler": snapshot_save,
        },
        "snapshot_load": {
            "description": "Load snapshot",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": snapshot_load,
        },
        "checkpoint_update": {
            "description": "Update checkpoint",
            "input_schema": {
                "type": "object",
                "properties": {
                    "last_applied_seq": {"type": "integer"},
                    "snapshot_path": {"type": ["string", "null"]},
                    "checkpoint_id": {"type": ["string", "null"]},
                },
                "required": ["last_applied_seq"],
            },
            "handler": checkpoint_update,
        },
        "checkpoint_read": {
            "description": "Read checkpoint",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": checkpoint_read,
        },
        "roll_forward_replay": {
            "description": "Replay journal",
            "input_schema": {
                "type": "object",
                "properties": {
                    "checkpoint_path": {"type": ["string", "null"]},
                    "snapshot_path": {"type": ["string", "null"]},
                    "start_seq": {"type": ["integer", "null"]},
                    "end_seq": {"type": ["integer", "null"]},
                },
                "required": [],
            },
            "handler": roll_forward_replay,
        },
        "continue_state_rebuild": {
            "description": "Rebuild state",
            "input_schema": {
                "type": "object",
                "properties": {
                    "checkpoint_path": {"type": ["string", "null"]},
                    "snapshot_path": {"type": ["string", "null"]},
                    "start_seq": {"type": ["integer", "null"]},
                    "end_seq": {"type": ["integer", "null"]},
                    "session_id": {"type": ["string", "null"]},
                },
                "required": [],
            },
            "handler": continue_state_rebuild,
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
            "description": "Generate resume brief",
            "input_schema": {
                "type": "object",
                "properties": {"max_chars": {"type": ["integer", "null"]}},
                "required": [],
            },
            "handler": ops_resume_brief,
        },
        "ops_start_task": {
            "description": "Record task start",
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
            "description": "Record task update",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status": {"type": ["string", "null"]},
                    "note": {"type": ["string", "null"]},
                    "task_id": {"type": ["string", "null"]},
                    "session_id": {"type": ["string", "null"]},
                    "agent_id": {"type": ["string", "null"]},
                },
                "required": [],
            },
            "handler": ops_update_task,
        },
        "ops_end_task": {
            "description": "Record task end",
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
        "ops_capture_state": {
            "description": "Snapshot and checkpoint state",
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
