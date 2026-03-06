from __future__ import annotations

import json
import uuid
from typing import Any, Dict

from .ops_tools import sanitize_args, summarize_result
from .repo_context import RepoContext
from .state_store import StateStore


class ToolRouter:
    def __init__(
        self,
        tool_registry: Dict[str, Any],
        repo_context: RepoContext,
        state_store: StateStore,
    ) -> None:
        self.tool_registry = tool_registry
        self.repo_context = repo_context
        self.state_store = state_store
        self.alias_map = {
            "journal.append": "journal_append",
            "snapshot.save": "snapshot_save",
            "snapshot.load": "snapshot_load",
            "checkpoint.update": "checkpoint_update",
            "checkpoint.read": "checkpoint_read",
            "roll_forward.replay": "roll_forward_replay",
            "continue.state_rebuild": "continue_state_rebuild",
            "tx.event_append": "tx_event_append",
            "tx.state_save": "tx_state_save",
            "tx.state_rebuild": "tx_state_rebuild",
            "session.capture_context": "session_capture_context",
            "repo.verify": "repo_verify",
            "repo.commit": "repo_commit",
            "repo.status_summary": "repo_status_summary",
            "repo.commit_message_suggest": "repo_commit_message_suggest",
            "tests.suggest": "tests_suggest",
            "tests.suggest_from_failures": "tests_suggest_from_failures",
            "ops.compact_context": "ops_compact_context",
            "ops.handoff_export": "ops_handoff_export",
            "ops.resume_brief": "ops_resume_brief",
            "ops.start_task": "ops_start_task",
            "ops.update_task": "ops_update_task",
            "ops.end_task": "ops_end_task",
            "ops.capture_state": "ops_capture_state",
            "ops.task_summary": "ops_task_summary",
            "ops.observability_summary": "ops_observability_summary",
        }

    def tools_list(self) -> Dict[str, Any]:
        tools = []
        for name, spec in self.tool_registry.items():
            input_schema = dict(spec["input_schema"])
            properties = dict(input_schema.get("properties") or {})
            properties["workspace_root"] = {"type": ["string", "null"]}
            properties["truncate_limit"] = {"type": ["integer", "null"]}
            input_schema["properties"] = properties
            input_schema["required"] = list(input_schema.get("required") or [])
            tools.append(
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": input_schema,
                }
            )
        return {"tools": tools}

    def tools_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        resolved_name = name
        if resolved_name not in self.tool_registry:
            resolved_name = self.alias_map.get(resolved_name, resolved_name)

        if resolved_name not in self.tool_registry:
            raise ValueError(f"Unknown tool: {name}")

        tool_spec = self.tool_registry[resolved_name]
        input_schema = tool_spec.get("input_schema") or {}
        required_fields = list(input_schema.get("required") or [])
        if required_fields:
            if not arguments:
                missing_list = ", ".join(required_fields)
                raise ValueError(f"Missing required argument(s): {missing_list}")
            missing = [
                field
                for field in required_fields
                if field not in arguments or arguments.get(field) is None
            ]
            if missing:
                missing_list = ", ".join(missing)
                raise ValueError(f"Missing required argument(s): {missing_list}")

        previous_root = self.repo_context.get_repo_root()
        workspace_root = arguments.get("workspace_root") if arguments else None
        missing_workspace_root = not (
            isinstance(workspace_root, str) and workspace_root.strip()
        )
        if not missing_workspace_root:
            resolved_root = self.repo_context.resolve_workspace_root(
                workspace_root.strip()
            )
            self.repo_context.set_repo_root(resolved_root)
            arguments = {k: v for k, v in arguments.items() if k != "workspace_root"}

        truncate_limit = None
        if arguments and "truncate_limit" in arguments:
            raw_limit = arguments.get("truncate_limit")
            if isinstance(raw_limit, int) and raw_limit > 0:
                truncate_limit = raw_limit
            arguments = {k: v for k, v in arguments.items() if k != "truncate_limit"}

        handler = tool_spec["handler"]
        call_id = str(uuid.uuid4())
        self.state_store.journal_safe(
            "tool.call",
            {
                "call_id": call_id,
                "tool": resolved_name,
                "args": sanitize_args(arguments),
            },
        )
        try:
            result = handler(**arguments) if arguments else handler()  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            self.state_store.journal_safe(
                "tool.result", {"call_id": call_id, "ok": False, "error": str(exc)}
            )
            raise
        finally:
            self.repo_context.set_repo_root(previous_root)

        summary_limit = truncate_limit if truncate_limit is not None else 2000
        result_payload = summarize_result(result, limit=summary_limit)
        if missing_workspace_root:
            hint = "workspace_root is missing; pass CWD as workspace_root."
            if isinstance(result_payload, dict):
                warnings = list(result_payload.get("warnings") or [])
                warnings.append({"code": "workspace_root.missing", "message": hint})
                result_payload["warnings"] = warnings
            else:
                result_payload = {
                    "result": result_payload,
                    "warnings": [{"code": "workspace_root.missing", "message": hint}],
                }
        self.state_store.journal_safe(
            "tool.result",
            {"call_id": call_id, "ok": True, "result": result_payload},
        )
        content_payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result_payload, ensure_ascii=False),
                }
            ]
        }
        return content_payload
