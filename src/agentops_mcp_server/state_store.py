from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .repo_context import RepoContext

TX_EVENT_TYPES = {
    "tx.begin",
    "tx.step.enter",
    "tx.file_intent.add",
    "tx.file_intent.update",
    "tx.file_intent.complete",
    "tx.verify.start",
    "tx.verify.pass",
    "tx.verify.fail",
    "tx.commit.start",
    "tx.commit.done",
    "tx.commit.fail",
    "tx.end.done",
    "tx.end.blocked",
    "tx.user_intent.set",
}

FILE_INTENT_OPERATIONS = {"create", "update", "delete", "move", "rename"}
FILE_INTENT_STATE_ORDER = {"planned": 0, "started": 1, "applied": 2, "verified": 3}
TX_STATUS_VALUES = {
    "planned",
    "in-progress",
    "checking",
    "verified",
    "committed",
    "done",
    "blocked",
}
VERIFY_STATUS_VALUES = {"not_started", "running", "passed", "failed"}
COMMIT_STATUS_VALUES = {"not_started", "running", "passed", "failed"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    DIAGNOSTIC_KEYS = {
        "error",
        "reason",
        "validation_point",
        "event_sequence",
        "active_tx_context",
        "expected_state",
        "observed_state",
        "observed_mismatch",
        "session_context",
    }

    def __init__(self, repo_context: RepoContext) -> None:
        self.repo_context = repo_context

    def ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_text(self, path: Path, content: str) -> None:
        self.ensure_parent(path)
        path.write_text(content, encoding="utf-8")

    def append_json_line(self, path: Path, payload: Dict[str, Any]) -> None:
        self.ensure_parent(path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _current_active_tx_context(self) -> Dict[str, Any]:
        active_tx = self._load_active_tx()
        if not isinstance(active_tx, dict):
            return {
                "tx_id": "none",
                "ticket_id": "none",
                "status": "unknown",
                "phase": "unknown",
                "current_step": "none",
                "next_action": "",
                "session_id": "",
            }
        return {
            "tx_id": active_tx.get("tx_id")
            if isinstance(active_tx.get("tx_id"), str)
            else "none",
            "ticket_id": active_tx.get("ticket_id")
            if isinstance(active_tx.get("ticket_id"), str)
            else "none",
            "status": active_tx.get("status")
            if isinstance(active_tx.get("status"), str)
            else "unknown",
            "phase": active_tx.get("phase")
            if isinstance(active_tx.get("phase"), str)
            else "unknown",
            "current_step": active_tx.get("current_step")
            if isinstance(active_tx.get("current_step"), str)
            else "none",
            "next_action": active_tx.get("next_action")
            if isinstance(active_tx.get("next_action"), str)
            else "",
            "session_id": active_tx.get("session_id")
            if isinstance(active_tx.get("session_id"), str)
            else "",
        }

    def _extract_event_sequence(
        self, tool_input: Dict[str, Any], tool_output: Any
    ) -> Dict[str, Any]:
        last_record = self.read_last_json_line(self.repo_context.tx_event_log)
        last_seq = last_record.get("seq") if isinstance(last_record, dict) else None

        sequence: Dict[str, Any] = {
            "last_logged_seq": last_seq if isinstance(last_seq, int) else None,
        }

        start_seq = tool_input.get("start_seq")
        if isinstance(start_seq, int):
            sequence["start_seq"] = start_seq

        end_seq = tool_input.get("end_seq")
        if isinstance(end_seq, int):
            sequence["end_seq"] = end_seq
        elif end_seq is None and "end_seq" in tool_input:
            sequence["end_seq"] = None

        if isinstance(tool_output, dict):
            for key in ("last_applied_seq", "rebuild_invalid_seq", "seq"):
                value = tool_output.get(key)
                if isinstance(value, int):
                    sequence[key] = value
            observed_mismatch = tool_output.get("observed_mismatch")
            if isinstance(observed_mismatch, dict):
                mismatch_seq = observed_mismatch.get("last_applied_seq")
                if isinstance(mismatch_seq, int):
                    sequence["observed_last_applied_seq"] = mismatch_seq

        return sequence

    def _normalize_tool_diagnostics(
        self, tool_name: str, tool_input: Dict[str, Any], tool_output: Any
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        if not isinstance(tool_output, dict):
            return tool_output, None

        diagnostics = {
            key: tool_output[key] for key in self.DIAGNOSTIC_KEYS if key in tool_output
        }

        if "validation_point" not in diagnostics:
            diagnostics["validation_point"] = tool_name

        if "event_sequence" not in diagnostics:
            diagnostics["event_sequence"] = self._extract_event_sequence(
                tool_input, tool_output
            )

        if "active_tx_context" not in diagnostics:
            diagnostics["active_tx_context"] = self._current_active_tx_context()

        if "session_context" not in diagnostics:
            diagnostics["session_context"] = {
                "requested_session_id": tool_input.get("session_id")
                if isinstance(tool_input.get("session_id"), str)
                else "",
                "active_session_id": diagnostics["active_tx_context"].get(
                    "session_id", ""
                ),
            }

        normalized_output = dict(tool_output)
        normalized_output["diagnostics"] = diagnostics
        return normalized_output, diagnostics

    def log_tool_error(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
    ) -> Dict[str, Any]:
        path = self.repo_context.state_artifact_path("errors")
        normalized_output, diagnostics = self._normalize_tool_diagnostics(
            tool_name, tool_input, tool_output
        )
        record = {
            "ts": now_iso(),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": normalized_output,
        }
        if isinstance(diagnostics, dict):
            record["diagnostics"] = diagnostics
        self.append_json_line(path, record)
        return {"ok": True, "path": str(path)}

    def read_json_file(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def read_last_json_line(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
        return None

    def _require_str(self, value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    def _require_payload_str(
        self, payload: Dict[str, Any], name: str, allow_empty: bool = False
    ) -> str:
        value = payload.get(name)
        if not isinstance(value, str):
            raise ValueError(f"payload.{name} is required")
        if not allow_empty and not value.strip():
            raise ValueError(f"payload.{name} is required")
        return value if allow_empty else value.strip()

    def _validate_tx_event_type(self, event_type: str) -> None:
        if event_type not in TX_EVENT_TYPES:
            raise ValueError("event_type is not defined in taxonomy")

    def _validate_tx_event_payload(
        self, event_type: str, payload: Dict[str, Any], step_id: str
    ) -> None:
        if event_type == "tx.begin":
            self._require_payload_str(payload, "ticket_id")
            return
        if event_type == "tx.step.enter":
            step_value = self._require_payload_str(payload, "step_id")
            if step_value != step_id:
                raise ValueError("payload.step_id must match step_id")
            return
        if event_type == "tx.file_intent.add":
            self._require_payload_str(payload, "path")
            operation = self._require_payload_str(payload, "operation")
            if operation not in FILE_INTENT_OPERATIONS:
                raise ValueError("payload.operation is invalid")
            self._require_payload_str(payload, "purpose")
            self._require_payload_str(payload, "planned_step")
            state = self._require_payload_str(payload, "state")
            if state != "planned":
                raise ValueError("payload.state must be planned")
            return
        if event_type == "tx.file_intent.update":
            self._require_payload_str(payload, "path")
            state = self._require_payload_str(payload, "state")
            if state not in {"started", "applied", "verified"}:
                raise ValueError("payload.state must be started, applied, or verified")
            return
        if event_type == "tx.file_intent.complete":
            self._require_payload_str(payload, "path")
            state = self._require_payload_str(payload, "state")
            if state != "verified":
                raise ValueError("payload.state must be verified")
            return
        if event_type == "tx.verify.start":
            return
        if event_type == "tx.verify.pass":
            if payload.get("ok") is not True:
                raise ValueError("payload.ok must be true")
            return
        if event_type == "tx.verify.fail":
            if payload.get("ok") is not False:
                raise ValueError("payload.ok must be false")
            return
        if event_type == "tx.commit.start":
            self._require_payload_str(payload, "message")
            self._require_payload_str(payload, "branch")
            self._require_payload_str(payload, "diff_summary")
            return
        if event_type == "tx.commit.done":
            self._require_payload_str(payload, "sha")
            self._require_payload_str(payload, "branch")
            self._require_payload_str(payload, "diff_summary")
            return
        if event_type == "tx.commit.fail":
            self._require_payload_str(payload, "error")
            return
        if event_type == "tx.end.done":
            self._require_payload_str(payload, "summary")
            return
        if event_type == "tx.end.blocked":
            self._require_payload_str(payload, "reason")
            return
        if event_type == "tx.user_intent.set":
            self._require_payload_str(payload, "user_intent")
            return

    def _intent_state_rank(self, state: Any) -> int:
        if not isinstance(state, str):
            return -1
        return FILE_INTENT_STATE_ORDER.get(state, -1)

    def _load_active_tx(self) -> Optional[Dict[str, Any]]:
        state = self.read_json_file(self.repo_context.tx_state)
        if isinstance(state, dict):
            active_tx = state.get("active_tx")
            if isinstance(active_tx, dict):
                return active_tx
        return None

    def _tx_event_log_empty(self) -> bool:
        return self.read_last_json_line(self.repo_context.tx_event_log) is None

    def _validate_tx_event_invariants(
        self, event_type: str, payload: Dict[str, Any], step_id: str, tx_id: str
    ) -> None:
        active_tx = self._load_active_tx()
        if not active_tx:
            if event_type != "tx.begin":
                raise ValueError("tx.begin required before other events")
            return
        active_tx_id = active_tx.get("tx_id")
        active_tx_id_value = (
            active_tx_id.strip() if isinstance(active_tx_id, str) else ""
        )
        has_active_tx = bool(active_tx_id_value) and active_tx_id_value != "none"
        if has_active_tx and event_type != "tx.begin" and active_tx_id_value != tx_id:
            next_action = active_tx.get("next_action")
            next_action_value = (
                next_action.strip() if isinstance(next_action, str) else ""
            )
            next_action_hint = (
                f" Resume active transaction '{active_tx_id_value}' first"
                + (f" (next_action={next_action_value})." if next_action_value else ".")
            )
            raise ValueError(
                "tx_id does not match active transaction: "
                f"active_tx={active_tx_id_value}, requested_tx={tx_id}."
                + next_action_hint
            )

        status = active_tx.get("status")
        if has_active_tx and status in {"done", "blocked"} and event_type != "tx.begin":
            raise ValueError("event after terminal")

        if event_type == "tx.begin":
            if not has_active_tx:
                return
            status = active_tx.get("status")
            if status not in {"done", "blocked"}:
                if self._tx_event_log_empty():
                    return
                raise ValueError("active transaction already in progress")
            return

        if not has_active_tx:
            raise ValueError("tx.begin required before other events")

        file_intents = active_tx.get("file_intents")
        if not isinstance(file_intents, list):
            file_intents = []

        def _find_intent(path: str) -> Optional[Dict[str, Any]]:
            for intent in file_intents:
                if isinstance(intent, dict) and intent.get("path") == path:
                    return intent
            return None

        if event_type == "tx.file_intent.add":
            planned_step = payload.get("planned_step")
            current_step = active_tx.get("current_step")
            if (
                isinstance(current_step, str)
                and current_step.strip()
                and planned_step != current_step
            ):
                raise ValueError("planned_step must match current_step")
            path = payload.get("path") if isinstance(payload.get("path"), str) else ""
            if path and _find_intent(path) is not None:
                raise ValueError("file intent already exists for path")
            return

        if event_type in {"tx.file_intent.update", "tx.file_intent.complete"}:
            path = payload.get("path") if isinstance(payload.get("path"), str) else ""
            intent = _find_intent(path)
            if intent is None:
                raise ValueError("file intent missing for path")
            new_state = payload.get("state")
            current_state = intent.get("state")
            if self._intent_state_rank(new_state) < self._intent_state_rank(
                current_state
            ):
                raise ValueError("file intent state must be monotonic")
            if new_state == "verified":
                verify_state = (
                    active_tx.get("verify_state")
                    if isinstance(active_tx.get("verify_state"), dict)
                    else {}
                )
                if verify_state.get("status") != "passed":
                    raise ValueError("file intent verified requires verify.pass")
            return

        if event_type == "tx.verify.start":
            for intent in file_intents:
                if (
                    isinstance(intent, dict)
                    and intent.get("planned_step") == step_id
                    and intent.get("state") in {"planned", "started"}
                ):
                    raise ValueError("verify.start requires applied intents")
            return

        if event_type in {"tx.verify.pass", "tx.verify.fail"}:
            verify_state = (
                active_tx.get("verify_state")
                if isinstance(active_tx.get("verify_state"), dict)
                else {}
            )
            if verify_state.get("status") != "running":
                raise ValueError("verify result requires verify.start")
            return

        if event_type == "tx.commit.start":
            verify_state = (
                active_tx.get("verify_state")
                if isinstance(active_tx.get("verify_state"), dict)
                else {}
            )
            if verify_state.get("status") != "passed":
                raise ValueError("commit.start requires verify.pass")
            return

        if event_type in {"tx.commit.done", "tx.commit.fail"}:
            commit_state = (
                active_tx.get("commit_state")
                if isinstance(active_tx.get("commit_state"), dict)
                else {}
            )
            if commit_state.get("status") != "running":
                raise ValueError("commit result requires commit.start")
            return

    def next_tx_event_seq(self) -> int:
        last = self.read_last_json_line(self.repo_context.tx_event_log)
        if isinstance(last, dict):
            seq = last.get("seq")
            if isinstance(seq, int) and seq >= 0:
                return seq + 1
        return 1

    def tx_event_append(
        self,
        *,
        tx_id: str,
        ticket_id: str,
        event_type: str,
        phase: str,
        step_id: str,
        actor: Dict[str, Any],
        session_id: str,
        payload: Dict[str, Any],
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_tx_id = self._require_str(tx_id, "tx_id")
        resolved_ticket_id = self._require_str(ticket_id, "ticket_id")
        resolved_event_type = self._require_str(event_type, "event_type")
        resolved_phase = self._require_str(phase, "phase")
        resolved_step_id = self._require_str(step_id, "step_id")
        resolved_session_id = self._require_str(session_id, "session_id")
        if not isinstance(actor, dict):
            raise ValueError("actor is required")
        if not isinstance(payload, dict):
            raise ValueError("payload is required")

        self._validate_tx_event_type(resolved_event_type)
        self._validate_tx_event_payload(resolved_event_type, payload, resolved_step_id)
        self._validate_tx_event_invariants(
            resolved_event_type, payload, resolved_step_id, resolved_tx_id
        )

        seq = self.next_tx_event_seq()
        resolved_event_id = event_id or str(uuid.uuid4())
        rec: Dict[str, Any] = {
            "seq": seq,
            "event_id": resolved_event_id,
            "ts": now_iso(),
            "project_root": str(self.repo_context.get_repo_root()),
            "tx_id": resolved_tx_id,
            "ticket_id": resolved_ticket_id,
            "event_type": resolved_event_type,
            "phase": resolved_phase,
            "step_id": resolved_step_id,
            "actor": actor,
            "session_id": resolved_session_id,
            "payload": payload,
        }
        self.ensure_parent(self.repo_context.tx_event_log)
        with self.repo_context.tx_event_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {"ok": True, "seq": seq, "event_id": resolved_event_id}

    def _validate_tx_state(self, state: Dict[str, Any]) -> None:
        schema_version = state.get("schema_version")
        if schema_version != "0.4.0":
            raise ValueError("schema_version must be 0.4.0")
        if not isinstance(state.get("last_applied_seq"), int):
            raise ValueError("last_applied_seq is required")
        if not isinstance(state.get("updated_at"), str):
            raise ValueError("updated_at is required")

        active_tx = state.get("active_tx")
        if not isinstance(active_tx, dict):
            raise ValueError("active_tx is required")

        tx_id = active_tx.get("tx_id")
        if not isinstance(tx_id, str) or not tx_id.strip():
            raise ValueError("active_tx.tx_id is required")
        ticket_id = active_tx.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            raise ValueError("active_tx.ticket_id is required")
        status = active_tx.get("status")
        if not isinstance(status, str) or status not in TX_STATUS_VALUES:
            raise ValueError("active_tx.status is invalid")
        phase = active_tx.get("phase")
        if not isinstance(phase, str) or phase not in TX_STATUS_VALUES:
            raise ValueError("active_tx.phase is invalid")
        if status != phase:
            raise ValueError("active_tx.phase must match status")
        current_step = active_tx.get("current_step")
        if not isinstance(current_step, str) or not current_step.strip():
            raise ValueError("active_tx.current_step is required")
        next_action = active_tx.get("next_action")
        if not isinstance(next_action, str) or not next_action.strip():
            raise ValueError("active_tx.next_action is required")
        if not isinstance(active_tx.get("file_intents"), list):
            raise ValueError("active_tx.file_intents is required")

        semantic_summary = active_tx.get("semantic_summary")
        if not isinstance(semantic_summary, str) or not semantic_summary.strip():
            raise ValueError("active_tx.semantic_summary is required")

        if "user_intent" not in active_tx:
            raise ValueError("active_tx.user_intent is required")
        user_intent = active_tx.get("user_intent")
        if user_intent is not None and not isinstance(user_intent, str):
            raise ValueError("active_tx.user_intent must be string or null")

        verify_state = active_tx.get("verify_state")
        if not isinstance(verify_state, dict):
            raise ValueError("active_tx.verify_state is required")
        verify_status = verify_state.get("status")
        if (
            not isinstance(verify_status, str)
            or verify_status not in VERIFY_STATUS_VALUES
        ):
            raise ValueError("active_tx.verify_state.status is invalid")

        commit_state = active_tx.get("commit_state")
        if not isinstance(commit_state, dict):
            raise ValueError("active_tx.commit_state is required")
        commit_status = commit_state.get("status")
        if (
            not isinstance(commit_status, str)
            or commit_status not in COMMIT_STATUS_VALUES
        ):
            raise ValueError("active_tx.commit_state.status is invalid")

        integrity = state.get("integrity")
        if not isinstance(integrity, dict):
            raise ValueError("integrity is required")
        if not isinstance(integrity.get("state_hash"), str):
            raise ValueError("integrity.state_hash is required")
        if not isinstance(integrity.get("rebuilt_from_seq"), int):
            raise ValueError("integrity.rebuilt_from_seq is required")

    def tx_state_save(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if state is None:
            raise ValueError("state is required")
        resolved_state = dict(state)
        if not isinstance(resolved_state.get("updated_at"), str):
            resolved_state["updated_at"] = now_iso()
        self._validate_tx_state(resolved_state)
        self.write_text(
            self.repo_context.tx_state,
            json.dumps(resolved_state, ensure_ascii=False, indent=2) + "\n",
        )
        return {"ok": True, "path": str(self.repo_context.tx_state)}

    def tx_event_append_and_state_save(
        self,
        *,
        tx_id: str,
        ticket_id: str,
        event_type: str,
        phase: str,
        step_id: str,
        actor: Dict[str, Any],
        session_id: str,
        payload: Dict[str, Any],
        state: Dict[str, Any],
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        next_state = json.loads(json.dumps(state, ensure_ascii=False))
        active_tx = next_state.get("active_tx")
        if not isinstance(active_tx, dict):
            raise ValueError("state.active_tx is required")
        active_tx["tx_id"] = tx_id
        active_tx["ticket_id"] = ticket_id
        active_tx["status"] = phase
        active_tx["phase"] = phase
        active_tx["current_step"] = step_id
        active_tx["session_id"] = session_id

        if event_type == "tx.begin":
            active_tx["last_completed_step"] = ""
            active_tx["user_intent"] = None
            active_tx["verify_state"] = {
                "status": "not_started",
                "last_result": None,
            }
            active_tx["commit_state"] = {
                "status": "not_started",
                "last_result": None,
            }
            if not isinstance(active_tx.get("file_intents"), list):
                active_tx["file_intents"] = []
            active_tx["next_action"] = "tx.verify.start"
        elif event_type == "tx.step.enter":
            description = payload.get("description")
            if isinstance(description, str) and description.strip():
                active_tx["semantic_summary"] = f"Entered step {step_id}"
            if phase == "checking":
                active_tx["next_action"] = "tx.verify.start"
            elif phase == "verified":
                active_tx["next_action"] = "tx.commit.start"
            elif phase == "committed":
                active_tx["next_action"] = "tx.end.done"
            elif phase == "blocked":
                active_tx["next_action"] = "tx.end.blocked"
            elif phase == "done":
                active_tx["next_action"] = "tx.end.done"
            else:
                active_tx["next_action"] = "tx.verify.start"
        elif event_type == "tx.verify.start":
            active_tx["verify_state"] = {"status": "running", "last_result": payload}
            active_tx["next_action"] = "tx.verify.pass"
        elif event_type == "tx.verify.pass":
            active_tx["verify_state"] = {"status": "passed", "last_result": payload}
            active_tx["semantic_summary"] = "Verification passed"
            active_tx["next_action"] = "tx.commit.start"
        elif event_type == "tx.verify.fail":
            active_tx["verify_state"] = {"status": "failed", "last_result": payload}
            active_tx["semantic_summary"] = "Verification failed"
            active_tx["next_action"] = "fix and re-verify"
        elif event_type == "tx.commit.start":
            active_tx["commit_state"] = {"status": "running", "last_result": payload}
            active_tx["next_action"] = "tx.commit.done"
        elif event_type == "tx.commit.done":
            active_tx["commit_state"] = {"status": "passed", "last_result": payload}
            active_tx["semantic_summary"] = "Commit completed"
            active_tx["next_action"] = "tx.end.done"
        elif event_type == "tx.commit.fail":
            active_tx["commit_state"] = {"status": "failed", "last_result": payload}
            active_tx["semantic_summary"] = "Commit failed"
            active_tx["next_action"] = "tx.commit.start"
        elif event_type == "tx.user_intent.set":
            user_intent = payload.get("user_intent")
            if isinstance(user_intent, str):
                active_tx["user_intent"] = user_intent
            if not isinstance(active_tx.get("next_action"), str) or not active_tx.get(
                "next_action"
            ):
                active_tx["next_action"] = "tx.verify.start"
        elif event_type and event_type.startswith("tx.file_intent."):
            file_intents = active_tx.get("file_intents")
            if not isinstance(file_intents, list):
                file_intents = []
                active_tx["file_intents"] = file_intents
            path = payload.get("path") if isinstance(payload.get("path"), str) else ""
            intent = None
            for item in file_intents:
                if isinstance(item, dict) and item.get("path") == path:
                    intent = item
                    break
            if event_type == "tx.file_intent.add":
                if intent is None:
                    intent = {
                        "path": path,
                        "operation": payload.get("operation")
                        if isinstance(payload.get("operation"), str)
                        else "",
                        "purpose": payload.get("purpose")
                        if isinstance(payload.get("purpose"), str)
                        else "",
                        "planned_step": payload.get("planned_step")
                        if isinstance(payload.get("planned_step"), str)
                        else "",
                        "state": payload.get("state")
                        if isinstance(payload.get("state"), str)
                        else "planned",
                        "last_event_seq": 0,
                    }
                    file_intents.append(intent)
            elif intent is not None and isinstance(payload.get("state"), str):
                intent["state"] = payload.get("state")
            if intent is not None and isinstance(payload.get("state"), str):
                intent["state"] = payload.get("state")
        elif event_type == "tx.end.done":
            active_tx["semantic_summary"] = "Transaction ended"
            active_tx["next_action"] = "tx.end.done"
        elif event_type == "tx.end.blocked":
            active_tx["semantic_summary"] = "Transaction ended"
            active_tx["next_action"] = "tx.end.blocked"

        if not isinstance(active_tx.get("semantic_summary"), str) or not active_tx.get(
            "semantic_summary"
        ):
            active_tx["semantic_summary"] = f"Updated transaction {ticket_id}"
        if not isinstance(active_tx.get("next_action"), str) or not active_tx.get(
            "next_action"
        ):
            active_tx["next_action"] = "tx.verify.start"
        if not isinstance(active_tx.get("file_intents"), list):
            active_tx["file_intents"] = []

        event_result = self.tx_event_append(
            tx_id=tx_id,
            ticket_id=ticket_id,
            event_type=event_type,
            phase=phase,
            step_id=step_id,
            actor=actor,
            session_id=session_id,
            payload=payload,
            event_id=event_id,
        )
        event_seq = event_result["seq"]
        if event_type and event_type.startswith("tx.file_intent."):
            file_intents = active_tx.get("file_intents")
            if isinstance(file_intents, list):
                path = (
                    payload.get("path") if isinstance(payload.get("path"), str) else ""
                )
                for intent in file_intents:
                    if isinstance(intent, dict) and intent.get("path") == path:
                        intent["last_event_seq"] = event_seq
                        break
        next_state["last_applied_seq"] = event_seq
        integrity = next_state.get("integrity")
        if not isinstance(integrity, dict):
            integrity = {}
            next_state["integrity"] = integrity
        integrity["rebuilt_from_seq"] = event_seq
        integrity["drift_detected"] = False
        if not isinstance(integrity.get("active_tx_source"), str) or not integrity.get(
            "active_tx_source"
        ):
            integrity["active_tx_source"] = "materialized"

        try:
            self.tx_state_save(next_state)
        except Exception as exc:
            self.log_tool_error(
                tool_name="tx_event_append_and_state_save",
                tool_input={
                    "tx_id": tx_id,
                    "ticket_id": ticket_id,
                    "event_type": event_type,
                    "phase": phase,
                    "step_id": step_id,
                    "session_id": session_id,
                    "event_id": event_id,
                },
                tool_output={
                    "error": "event append succeeded but tx_state synchronization failed",
                    "reason": str(exc),
                    "validation_point": "tx_event_append_and_state_save",
                    "event_sequence": {
                        "last_logged_seq": event_seq,
                        "seq": event_seq,
                    },
                    "expected_state": {
                        "last_applied_seq": event_seq,
                        "rebuilt_from_seq": event_seq,
                        "tx_id": tx_id,
                        "ticket_id": ticket_id,
                        "status": phase,
                        "phase": phase,
                        "current_step": step_id,
                    },
                    "observed_state": {
                        "tx_state_path": str(self.repo_context.tx_state),
                    },
                },
            )
            raise RuntimeError(
                "canonical event appended but tx_state synchronization failed"
            ) from exc

        saved_state = self.read_json_file(self.repo_context.tx_state)
        if not isinstance(saved_state, dict):
            self.log_tool_error(
                tool_name="tx_event_append_and_state_save",
                tool_input={
                    "tx_id": tx_id,
                    "ticket_id": ticket_id,
                    "event_type": event_type,
                    "phase": phase,
                    "step_id": step_id,
                    "session_id": session_id,
                    "event_id": event_id,
                },
                tool_output={
                    "error": "event append succeeded but tx_state could not be reloaded",
                    "validation_point": "tx_event_append_and_state_save",
                    "event_sequence": {
                        "last_logged_seq": event_seq,
                        "seq": event_seq,
                    },
                    "expected_state": {
                        "last_applied_seq": event_seq,
                        "rebuilt_from_seq": event_seq,
                        "tx_id": tx_id,
                        "ticket_id": ticket_id,
                        "status": phase,
                        "phase": phase,
                        "current_step": step_id,
                    },
                    "observed_state": {
                        "tx_state_path": str(self.repo_context.tx_state),
                    },
                },
            )
            raise RuntimeError(
                "canonical event appended but tx_state synchronization could not be verified"
            )

        saved_active_tx = (
            saved_state.get("active_tx")
            if isinstance(saved_state.get("active_tx"), dict)
            else {}
        )
        saved_integrity = (
            saved_state.get("integrity")
            if isinstance(saved_state.get("integrity"), dict)
            else {}
        )

        if (
            saved_state.get("last_applied_seq") != event_seq
            or saved_integrity.get("rebuilt_from_seq") != event_seq
            or saved_active_tx.get("tx_id") != tx_id
            or saved_active_tx.get("ticket_id") != ticket_id
            or saved_active_tx.get("status") != phase
            or saved_active_tx.get("phase") != phase
            or saved_active_tx.get("current_step") != step_id
        ):
            self.log_tool_error(
                tool_name="tx_event_append_and_state_save",
                tool_input={
                    "tx_id": tx_id,
                    "ticket_id": ticket_id,
                    "event_type": event_type,
                    "phase": phase,
                    "step_id": step_id,
                    "session_id": session_id,
                    "event_id": event_id,
                },
                tool_output={
                    "error": "event append succeeded but materialized tx_state drifted",
                    "validation_point": "tx_event_append_and_state_save",
                    "event_sequence": {
                        "last_logged_seq": event_seq,
                        "seq": event_seq,
                    },
                    "expected_state": {
                        "last_applied_seq": event_seq,
                        "rebuilt_from_seq": event_seq,
                        "tx_id": tx_id,
                        "ticket_id": ticket_id,
                        "status": phase,
                        "phase": phase,
                        "current_step": step_id,
                    },
                    "observed_state": {
                        "last_applied_seq": saved_state.get("last_applied_seq"),
                        "rebuilt_from_seq": saved_integrity.get("rebuilt_from_seq"),
                        "tx_id": saved_active_tx.get("tx_id"),
                        "ticket_id": saved_active_tx.get("ticket_id"),
                        "status": saved_active_tx.get("status"),
                        "phase": saved_active_tx.get("phase"),
                        "current_step": saved_active_tx.get("current_step"),
                    },
                },
            )
            raise RuntimeError(
                "canonical event appended but tx_state synchronization drifted"
            )

        return {
            "ok": True,
            "seq": event_seq,
            "event_id": event_result["event_id"],
            "path": str(self.repo_context.tx_state),
        }
