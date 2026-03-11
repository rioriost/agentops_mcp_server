from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from .ops_tools import summarize_result
from .state_store import StateStore
from .tool_router import ToolRouter


def _write_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class JsonRpcServer:
    def __init__(self, tool_router: ToolRouter, state_store: StateStore) -> None:
        self.tool_router = tool_router
        self.state_store = state_store

    def _log_tool_failure(
        self,
        tool_name: Optional[str],
        tool_input: Any,
        tool_output: Any,
    ) -> None:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return
        if not self.state_store.repo_context.has_repo_root():
            return

        normalized_input = (
            tool_input if isinstance(tool_input, dict) else {"raw_input": tool_input}
        )
        normalized_output = summarize_result(tool_output, limit=4000)

        try:
            self.state_store.log_tool_error(
                tool_name=tool_name.strip(),
                tool_input=normalized_input,
                tool_output=normalized_output,
            )
        except Exception:
            return

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method")
        params = req.get("params") or {}
        req_id = req.get("id")

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "agentops-server", "version": "0.4.13"},
                "capabilities": {"tools": {}},
            }
        elif method == "initialized":
            result = None
        elif method == "shutdown":
            result = None
        elif method == "exit":
            sys.exit(0)
        elif method == "tools/list":
            result = self.tool_router.tools_list()
        elif method == "tools/call":
            name = params.get("name")
            raw_arguments = params.get("arguments")
            arguments = raw_arguments if raw_arguments is not None else {}
            if not isinstance(name, str):
                raise ValueError("tools/call requires 'name' (string)")
            if not isinstance(arguments, dict):
                raise ValueError("tools/call requires 'arguments' (object)")
            result = self.tool_router.tools_call(name, arguments)
            try:
                parsed_result = result
                if isinstance(result, dict):
                    content = result.get("content")
                    if isinstance(content, list) and content:
                        first_item = content[0]
                        if isinstance(first_item, dict):
                            text = first_item.get("text")
                            if isinstance(text, str) and text.strip():
                                parsed_result = json.loads(text)
                if isinstance(parsed_result, dict) and parsed_result.get("ok") is False:
                    self._log_tool_failure(
                        tool_name=name,
                        tool_input=arguments,
                        tool_output=parsed_result,
                    )
            except Exception:
                pass
        else:
            raise ValueError(f"Unknown method: {method}")

        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def run(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("Request must be a JSON object")
                req_id = req.get("id") if isinstance(req, dict) else None
                resp = self.handle_request(req)
                if resp is not None:
                    _write_json(resp)
            except Exception as exc:  # noqa: BLE001
                req_id = None
                try:
                    req_id = req.get("id") if isinstance(req, dict) else None
                except Exception:  # noqa: BLE001
                    req_id = None

                if req_id is not None:
                    error_payload: Dict[str, Any] = {
                        "code": -32000,
                        "message": str(exc),
                    }
                    structured_payload = (
                        exc.args[0] if getattr(exc, "args", ()) else None
                    )
                    if isinstance(structured_payload, dict):
                        reason = structured_payload.get("reason")
                        if isinstance(reason, str) and reason.strip():
                            error_payload["message"] = reason.strip()
                        error_payload["data"] = structured_payload
                    if isinstance(exc, ValueError):
                        error_payload["code"] = -32602
                    _write_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": error_payload,
                        }
                    )
