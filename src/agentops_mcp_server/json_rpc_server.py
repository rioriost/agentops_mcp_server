from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from .state_store import StateStore
from .tool_router import ToolRouter


def _write_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class JsonRpcServer:
    def __init__(self, tool_router: ToolRouter, state_store: StateStore) -> None:
        self.tool_router = tool_router
        self.state_store = state_store

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method")
        params = req.get("params") or {}
        req_id = req.get("id")

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "agentops-server", "version": "0.2.0"},
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
                self.state_store.journal_safe(
                    "error", {"message": str(exc), "kind": "request"}
                )
                if req_id is not None:
                    _write_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32000, "message": str(exc)},
                        }
                    )
