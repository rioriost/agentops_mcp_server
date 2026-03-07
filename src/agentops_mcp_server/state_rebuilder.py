from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .repo_context import RepoContext
from .state_store import (
    FILE_INTENT_OPERATIONS,
    FILE_INTENT_STATE_ORDER,
    TX_EVENT_TYPES,
    StateStore,
)


class StateRebuilder:
    def __init__(self, repo_context: RepoContext, state_store: StateStore) -> None:
        self.repo_context = repo_context
        self.state_store = state_store

    def _truncate_text(self, value: Optional[str], limit: int = 2000) -> Optional[str]:
        if value is None:
            return None
        if limit <= 0:
            return ""
        if len(value) <= limit:
            return value
        suffix = "...(truncated)"
        prefix = value[:limit].rstrip()
        return prefix + suffix

    def resolve_path(self, path_value: Optional[str], default: Path) -> Path:
        if path_value is None:
            return default
        candidate = Path(path_value)
        if candidate.is_absolute():
            return candidate
        return self.repo_context.get_repo_root() / candidate

    def read_tx_event_log(
        self,
        start_seq: int,
        end_seq: Optional[int] = None,
        event_log_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        if start_seq < 0:
            raise ValueError("start_seq must be >= 0")
        if end_seq is not None and end_seq < start_seq:
            raise ValueError("end_seq must be >= start_seq")

        path = event_log_path or self.repo_context.tx_event_log
        events: List[Dict[str, Any]] = []
        invalid_lines = 0
        last_seq = start_seq

        if not path.exists():
            return {
                "events": events,
                "invalid_lines": invalid_lines,
                "last_seq": last_seq,
                "path": str(path),
            }

        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue
                if not isinstance(rec, dict):
                    invalid_lines += 1
                    continue
                seq = rec.get("seq")
                if not isinstance(seq, int):
                    invalid_lines += 1
                    continue
                if seq <= start_seq:
                    continue
                if end_seq is not None and seq > end_seq:
                    continue
                events.append(rec)
                if seq > last_seq:
                    last_seq = seq

        return {
            "events": events,
            "invalid_lines": invalid_lines,
            "last_seq": last_seq,
            "path": str(path),
        }

    def read_recent_tx_events(self, max_events: int) -> List[Dict[str, Any]]:
        if max_events <= 0:
            return []
        path = self.repo_context.tx_event_log
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        events: List[Dict[str, Any]] = []
        for raw_line in reversed(lines):
            if len(events) >= max_events:
                break
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            events.append(rec)
        events.reverse()
        return events

    def _init_active_tx(
        self, tx_id: str, ticket_id: str, phase: str, step_id: str
    ) -> Dict[str, Any]:
        return {
            "tx_id": tx_id or "none",
            "ticket_id": ticket_id or "none",
            "status": phase,
            "phase": phase,
            "current_step": step_id,
            "last_completed_step": "",
            "next_action": "",
            "semantic_summary": "",
            "user_intent": None,
            "verify_state": {"status": "not_started", "last_result": None},
            "commit_state": {"status": "not_started", "last_result": None},
            "file_intents": [],
            "_last_event_seq": -1,
            "_terminal": False,
        }

    def _init_tx_state(self) -> Dict[str, Any]:
        return {
            "schema_version": "0.4.0",
            "active_tx": self._init_active_tx("", "", "planned", "none"),
            "last_applied_seq": 0,
            "integrity": {"state_hash": "", "rebuilt_from_seq": 0},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _compute_state_hash(self, state: Dict[str, Any]) -> str:
        sanitized = json.loads(json.dumps(state, ensure_ascii=False))
        sanitized.pop("updated_at", None)
        integrity = sanitized.get("integrity")
        if isinstance(integrity, dict):
            integrity.pop("state_hash", None)
        active_tx = sanitized.get("active_tx")
        if isinstance(active_tx, dict):
            active_tx.pop("_last_event_seq", None)
            active_tx.pop("_terminal", None)
        payload = json.dumps(
            sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _validate_tx_event(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        if not isinstance(event.get("seq"), int):
            return False, "missing seq"
        if not isinstance(event.get("tx_id"), str):
            return False, "missing tx_id"
        if not isinstance(event.get("ticket_id"), str):
            return False, "missing ticket_id"
        event_type = event.get("event_type")
        if not isinstance(event_type, str):
            return False, "missing event_type"
        if event_type not in TX_EVENT_TYPES:
            return False, "unknown event_type"
        if not isinstance(event.get("phase"), str):
            return False, "missing phase"
        if not isinstance(event.get("step_id"), str):
            return False, "missing step_id"
        if not isinstance(event.get("actor"), dict):
            return False, "missing actor"
        if not isinstance(event.get("session_id"), str):
            return False, "missing session_id"
        if not isinstance(event.get("payload"), dict):
            return False, "missing payload"
        return True, ""

    def _intent_state_rank(self, state: Any) -> int:
        if not isinstance(state, str):
            return -1
        return FILE_INTENT_STATE_ORDER.get(state, -1)

    def _validate_tx_event_payload(
        self, event_type: str, payload: Dict[str, Any], step_id: str
    ) -> Tuple[bool, str]:
        def _require_str(name: str) -> bool:
            value = payload.get(name)
            return isinstance(value, str) and value.strip() != ""

        if event_type == "tx.begin":
            return (_require_str("ticket_id"), "missing payload.ticket_id")
        if event_type == "tx.step.enter":
            if not _require_str("step_id"):
                return False, "missing payload.step_id"
            if payload.get("step_id") != step_id:
                return False, "payload.step_id must match step_id"
            return True, ""
        if event_type == "tx.file_intent.add":
            if not _require_str("path"):
                return False, "missing payload.path"
            if not _require_str("operation"):
                return False, "missing payload.operation"
            if payload.get("operation") not in FILE_INTENT_OPERATIONS:
                return False, "payload.operation is invalid"
            if not _require_str("purpose"):
                return False, "missing payload.purpose"
            if not _require_str("planned_step"):
                return False, "missing payload.planned_step"
            if payload.get("state") != "planned":
                return False, "payload.state must be planned"
            return True, ""
        if event_type == "tx.file_intent.update":
            if not _require_str("path"):
                return False, "missing payload.path"
            if payload.get("state") not in {"started", "applied", "verified"}:
                return False, "payload.state must be started, applied, or verified"
            return True, ""
        if event_type == "tx.file_intent.complete":
            if not _require_str("path"):
                return False, "missing payload.path"
            if payload.get("state") != "verified":
                return False, "payload.state must be verified"
            return True, ""
        if event_type == "tx.verify.pass":
            return (payload.get("ok") is True, "payload.ok must be true")
        if event_type == "tx.verify.fail":
            return (payload.get("ok") is False, "payload.ok must be false")
        if event_type == "tx.commit.start":
            if not _require_str("message"):
                return False, "missing payload.message"
            if not _require_str("branch"):
                return False, "missing payload.branch"
            if not _require_str("diff_summary"):
                return False, "missing payload.diff_summary"
            return True, ""
        if event_type == "tx.commit.done":
            if not _require_str("sha"):
                return False, "missing payload.sha"
            if not _require_str("branch"):
                return False, "missing payload.branch"
            if not _require_str("diff_summary"):
                return False, "missing payload.diff_summary"
            return True, ""
        if event_type == "tx.commit.fail":
            return (_require_str("error"), "missing payload.error")
        if event_type == "tx.end.done":
            return (_require_str("summary"), "missing payload.summary")
        if event_type == "tx.end.blocked":
            return (_require_str("reason"), "missing payload.reason")
        if event_type == "tx.user_intent.set":
            return (_require_str("user_intent"), "missing payload.user_intent")
        return True, ""

    def _init_tx_context(self) -> Dict[str, Any]:
        return {
            "seen_begin": False,
            "terminal": False,
            "steps": set(),
            "intent_states": {},
            "intent_steps": {},
            "verify_started_steps": set(),
            "verify_passed": False,
            "commit_started": False,
        }

    def _validate_tx_event_invariants(
        self, context: Dict[str, Any], event: Dict[str, Any]
    ) -> Tuple[bool, str]:
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        step_id = event.get("step_id") if isinstance(event.get("step_id"), str) else ""

        if context.get("terminal"):
            return False, "event after terminal"

        if event_type == "tx.begin":
            if context.get("seen_begin"):
                return False, "duplicate tx.begin"
            context["seen_begin"] = True
        else:
            if not context.get("seen_begin"):
                return False, "tx.begin required"

        if event_type == "tx.step.enter" and step_id:
            context["steps"].add(step_id)

        if event_type == "tx.file_intent.add":
            path = payload.get("path")
            planned_step = payload.get("planned_step")
            if not isinstance(path, str) or not path.strip():
                return False, "missing payload.path"
            if (
                not isinstance(planned_step, str)
                or planned_step not in context["steps"]
            ):
                return False, "planned_step must reference a prior step"
            if path in context["intent_states"]:
                return False, "file intent already exists"
            context["intent_states"][path] = payload.get("state")
            context["intent_steps"][path] = planned_step

        if event_type in {"tx.file_intent.update", "tx.file_intent.complete"}:
            path = payload.get("path")
            if not isinstance(path, str) or not path.strip():
                return False, "missing payload.path"
            if path not in context["intent_states"]:
                return False, "file intent missing for path"
            new_state = payload.get("state")
            if self._intent_state_rank(new_state) < self._intent_state_rank(
                context["intent_states"].get(path)
            ):
                return False, "file intent state must be monotonic"
            if new_state == "verified" and not context.get("verify_passed"):
                return False, "file intent verified requires verify.pass"
            if event_type == "tx.file_intent.complete" and new_state != "verified":
                return False, "file intent complete requires verified"
            context["intent_states"][path] = new_state

        if event_type == "tx.verify.start":
            required_rank = FILE_INTENT_STATE_ORDER["applied"]
            for path, planned_step in context["intent_steps"].items():
                if planned_step == step_id:
                    state = context["intent_states"].get(path)
                    if self._intent_state_rank(state) < required_rank:
                        return False, "verify.start requires applied intents"
            context["verify_started_steps"].add(step_id)

        if event_type in {"tx.verify.pass", "tx.verify.fail"}:
            if step_id not in context["verify_started_steps"]:
                return False, "verify result requires verify.start"
            if event_type == "tx.verify.pass":
                context["verify_passed"] = True

        if event_type == "tx.commit.start":
            if not context.get("verify_passed"):
                return False, "commit.start requires verify.pass"
            context["commit_started"] = True

        if event_type in {"tx.commit.done", "tx.commit.fail"}:
            if not context.get("commit_started"):
                return False, "commit result requires commit.start"

        if isinstance(event_type, str) and event_type.startswith("tx.end."):
            context["terminal"] = True

        return True, ""

    def _update_semantic_summary(
        self, event_type: str, payload: Dict[str, Any], step_id: str
    ) -> str:
        if event_type == "tx.begin":
            ticket_id = (
                payload.get("ticket_id")
                if isinstance(payload.get("ticket_id"), str)
                else ""
            )
            return f"Started transaction {ticket_id}".strip()
        if event_type == "tx.step.enter":
            return f"Entered step {step_id}"
        if event_type == "tx.file_intent.add":
            path = (
                payload.get("path") if isinstance(payload.get("path"), str) else "file"
            )
            operation = (
                payload.get("operation")
                if isinstance(payload.get("operation"), str)
                else "update"
            )
            return f"Planned {operation} for {path}"
        if event_type == "tx.file_intent.update":
            path = (
                payload.get("path") if isinstance(payload.get("path"), str) else "file"
            )
            state = (
                payload.get("state")
                if isinstance(payload.get("state"), str)
                else "updated"
            )
            return f"Updated intent for {path} to {state}"
        if event_type == "tx.file_intent.complete":
            path = (
                payload.get("path") if isinstance(payload.get("path"), str) else "file"
            )
            return f"Completed intent for {path}"
        if event_type == "tx.verify.pass":
            return "Verification passed"
        if event_type == "tx.verify.fail":
            return "Verification failed"
        if event_type == "tx.commit.done":
            return "Commit completed"
        if event_type == "tx.commit.fail":
            return "Commit failed"
        if event_type.startswith("tx.end."):
            return "Transaction ended"
        return ""

    def _apply_tx_event_to_state(
        self, active_tx: Dict[str, Any], event: Dict[str, Any]
    ) -> None:
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        phase = event.get("phase")
        step_id = event.get("step_id")
        seq = event.get("seq")

        if isinstance(phase, str):
            active_tx["status"] = phase
            active_tx["phase"] = phase

        if isinstance(step_id, str) and event_type == "tx.step.enter":
            active_tx["current_step"] = step_id

        if event_type == "tx.begin":
            active_tx["tx_id"] = event.get("tx_id")
            active_tx["ticket_id"] = event.get("ticket_id")
            active_tx["current_step"] = step_id if isinstance(step_id, str) else "none"
        if event_type and event_type.startswith("tx.file_intent."):
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
                    "last_event_seq": seq if isinstance(seq, int) else 0,
                }
                file_intents.append(intent)
            else:
                if isinstance(payload.get("state"), str):
                    intent["state"] = payload.get("state")
                if isinstance(seq, int):
                    intent["last_event_seq"] = seq

        if event_type == "tx.verify.start":
            active_tx["verify_state"] = {"status": "running", "last_result": payload}
        if event_type == "tx.verify.pass":
            active_tx["verify_state"] = {"status": "passed", "last_result": payload}
        if event_type == "tx.verify.fail":
            active_tx["verify_state"] = {"status": "failed", "last_result": payload}

        if event_type == "tx.commit.start":
            active_tx["commit_state"] = {"status": "running", "last_result": payload}
        if event_type == "tx.commit.done":
            active_tx["commit_state"] = {"status": "passed", "last_result": payload}
        if event_type == "tx.commit.fail":
            active_tx["commit_state"] = {"status": "failed", "last_result": payload}

        if event_type == "tx.user_intent.set":
            user_intent = payload.get("user_intent")
            if isinstance(user_intent, str):
                active_tx["user_intent"] = user_intent

        summary = self._update_semantic_summary(
            event_type, payload, step_id if isinstance(step_id, str) else ""
        )
        if summary:
            active_tx["semantic_summary"] = summary

    def _derive_next_action(self, active_tx: Dict[str, Any]) -> str:
        status = active_tx.get("status")
        file_intents = active_tx.get("file_intents")
        semantic_summary = (
            active_tx.get("semantic_summary")
            if isinstance(active_tx.get("semantic_summary"), str)
            else ""
        )
        user_intent = (
            active_tx.get("user_intent")
            if isinstance(active_tx.get("user_intent"), str)
            else ""
        )
        intent_value = user_intent.strip().lower()
        intent_continue = intent_value in {"continue", "resume", "proceed"}
        summary_lower = semantic_summary.lower()

        verify_state = (
            active_tx.get("verify_state")
            if isinstance(active_tx.get("verify_state"), dict)
            else {}
        )
        commit_state = (
            active_tx.get("commit_state")
            if isinstance(active_tx.get("commit_state"), dict)
            else {}
        )

        if status == "planned":
            return "tx.begin"
        if status == "in-progress":
            if isinstance(file_intents, list) and file_intents:
                if any(
                    intent.get("state") in {"planned", "started"}
                    for intent in file_intents
                    if isinstance(intent, dict)
                ):
                    return "continue file intents"
                if all(
                    intent.get("state") in {"applied", "verified"}
                    for intent in file_intents
                    if isinstance(intent, dict)
                ):
                    return "tx.verify.start"
            if intent_continue:
                return "continue file intents"
            if "verify" in summary_lower:
                return "tx.verify.start"
            return "tx.verify.start"
        if status == "checking":
            if verify_state.get("status") == "not_started":
                return "tx.verify.start"
            if verify_state.get("status") == "failed":
                return "fix and re-verify"
        if status == "verified":
            if commit_state.get("status") == "not_started":
                return "tx.commit.start"
        if status == "committed":
            return "tx.end.done"
        if status == "blocked":
            return "tx.end.blocked"
        if status == "done":
            return "tx.end.done"
        return "tx.begin"

    def _tx_state_integrity_ok(self, state: Dict[str, Any], last_seq: int) -> bool:
        if state.get("schema_version") != "0.4.0":
            return False
        if not isinstance(state.get("last_applied_seq"), int):
            return False
        if state.get("last_applied_seq") != last_seq:
            return False
        integrity = state.get("integrity")
        if not isinstance(integrity, dict):
            return False
        if not isinstance(integrity.get("rebuilt_from_seq"), int):
            return False
        if not isinstance(integrity.get("state_hash"), str):
            return False
        if state.get("last_applied_seq") < integrity.get("rebuilt_from_seq"):
            return False
        return integrity.get("state_hash") == self._compute_state_hash(state)

    def rebuild_tx_state(
        self,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
        tx_state_path: Optional[str] = None,
        event_log_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_state_path = self.resolve_path(
            tx_state_path, self.repo_context.tx_state
        )
        existing_state = self.state_store.read_json_file(resolved_state_path)
        resolved_event_log = (
            self.resolve_path(event_log_path, self.repo_context.tx_event_log)
            if event_log_path is not None
            else self.repo_context.tx_event_log
        )

        if not resolved_event_log.exists():
            return {
                "ok": False,
                "reason": "tx_event_log missing",
                "path": str(resolved_event_log),
            }

        event_log = self.read_tx_event_log(
            start_seq=0, end_seq=end_seq, event_log_path=resolved_event_log
        )
        last_seq = (
            event_log.get("last_seq")
            if isinstance(event_log.get("last_seq"), int)
            else 0
        )

        if isinstance(existing_state, dict) and self._tx_state_integrity_ok(
            existing_state, last_seq
        ):
            active_tx = existing_state.get("active_tx")
            if isinstance(active_tx, dict):
                active_tx["next_action"] = self._derive_next_action(active_tx)
            integrity = existing_state.get("integrity")
            if isinstance(integrity, dict):
                existing_state["updated_at"] = datetime.now(timezone.utc).isoformat()
                integrity["state_hash"] = self._compute_state_hash(existing_state)
            return {
                "ok": True,
                "state": existing_state,
                "last_applied_seq": existing_state.get("last_applied_seq"),
                "event_log_path": str(resolved_event_log),
                "source": "materialized",
            }

        replay_start = start_seq if isinstance(start_seq, int) else 0
        event_log = self.read_tx_event_log(
            start_seq=replay_start, end_seq=end_seq, event_log_path=resolved_event_log
        )
        events = (
            event_log.get("events") if isinstance(event_log.get("events"), list) else []
        )
        invalid_lines = (
            event_log.get("invalid_lines")
            if isinstance(event_log.get("invalid_lines"), int)
            else 0
        )

        state = self._init_tx_state()
        state["last_applied_seq"] = replay_start
        state["integrity"]["rebuilt_from_seq"] = replay_start

        tx_states: Dict[str, Dict[str, Any]] = {}
        tx_contexts: Dict[str, Dict[str, Any]] = {}
        applied_event_ids: set[str] = set()
        dropped_events = 0
        last_valid_seq = replay_start
        invalid_reason = ""
        invalid_event: Optional[Dict[str, Any]] = None

        for event in events:
            if not isinstance(event, dict):
                break
            valid, reason = self._validate_tx_event(event)
            if not valid:
                invalid_reason = reason or "invalid event"
                invalid_event = event
                # Torn-state recovery: truncate at last valid seq and rebuild deterministically.
                break
            event_id = event.get("event_id")
            if isinstance(event_id, str) and event_id in applied_event_ids:
                dropped_events += 1
                continue

            tx_id = event.get("tx_id")
            ticket_id = event.get("ticket_id")
            phase = event.get("phase")
            step_id = event.get("step_id")
            active_tx = tx_states.get(tx_id)
            if active_tx is None:
                active_tx = self._init_active_tx(
                    tx_id if isinstance(tx_id, str) else "",
                    ticket_id if isinstance(ticket_id, str) else "",
                    phase if isinstance(phase, str) else "planned",
                    step_id if isinstance(step_id, str) else "none",
                )
            event_type = event.get("event_type")
            payload = (
                event.get("payload") if isinstance(event.get("payload"), dict) else {}
            )
            step_value = (
                event.get("step_id") if isinstance(event.get("step_id"), str) else ""
            )
            valid, reason = self._validate_tx_event_payload(
                event_type, payload, step_value
            )
            if not valid:
                invalid_reason = reason or "invalid payload"
                invalid_event = event
                break
            tx_context = tx_contexts.get(tx_id)
            if tx_context is None:
                tx_context = self._init_tx_context()
                tx_contexts[tx_id] = tx_context
            valid, reason = self._validate_tx_event_invariants(tx_context, event)
            if not valid:
                invalid_reason = reason or "invalid ordering"
                invalid_event = event
                break

            self._apply_tx_event_to_state(active_tx, event)
            if isinstance(event.get("seq"), int):
                active_tx["_last_event_seq"] = event.get("seq")
                last_valid_seq = event.get("seq")
            if isinstance(event.get("event_type"), str) and event.get(
                "event_type"
            ).startswith("tx.end."):
                active_tx["_terminal"] = True
            tx_states[tx_id] = active_tx
            if isinstance(event_id, str):
                applied_event_ids.add(event_id)

        candidates = []
        if invalid_reason:
            state["rebuild_warning"] = invalid_reason
            if isinstance(invalid_event, dict):
                state["rebuild_invalid_event"] = invalid_event
                if isinstance(invalid_event.get("seq"), int):
                    state["rebuild_invalid_seq"] = invalid_event.get("seq")
        else:
            candidates = [
                tx
                for tx in tx_states.values()
                if isinstance(tx, dict) and not tx.get("_terminal")
            ]
        if candidates:
            active_tx = max(
                candidates, key=lambda item: item.get("_last_event_seq", -1)
            )
            active_tx.pop("_last_event_seq", None)
            active_tx.pop("_terminal", None)
            if not active_tx.get("semantic_summary"):
                active_tx["semantic_summary"] = "Rebuilt state from tx event log."
            active_tx["next_action"] = self._derive_next_action(active_tx)
            state["active_tx"] = active_tx
        else:
            if not state["active_tx"].get("semantic_summary"):
                state["active_tx"]["semantic_summary"] = "No active transaction."
            state["active_tx"]["next_action"] = self._derive_next_action(
                state["active_tx"]
            )

        state["last_applied_seq"] = last_valid_seq
        state["integrity"]["rebuilt_from_seq"] = last_valid_seq
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["integrity"]["state_hash"] = self._compute_state_hash(state)

        return {
            "ok": True,
            "state": state,
            "last_applied_seq": last_valid_seq,
            "rebuilt_from_seq": state["integrity"]["rebuilt_from_seq"],
            "invalid_lines": invalid_lines,
            "dropped_events": dropped_events,
            "event_log_path": str(resolved_event_log),
            "source": "rebuild",
        }

    def parse_iso_ts(self, value: str) -> Optional[datetime]:
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def week_start_utc(self, dt: datetime) -> datetime:
        dt = dt.astimezone(timezone.utc)
        start = dt - timedelta(days=dt.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def read_first_event_with_ts(
        self,
        path: Path,
    ) -> Optional[Tuple[Dict[str, Any], datetime]]:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                ts_value = rec.get("ts")
                if not isinstance(ts_value, str):
                    continue
                parsed = self.parse_iso_ts(ts_value)
                if parsed is None:
                    continue
                return rec, parsed
        return None

    def rotate_journal_if_prev_week(self) -> Dict[str, Any]:
        journal_path = self.repo_context.journal
        if not journal_path.exists():
            return {
                "ok": False,
                "reason": "journal not found",
                "path": str(journal_path),
            }
        first = self.read_first_event_with_ts(journal_path)
        if not first:
            return {"ok": False, "reason": "no valid journal timestamps"}
        _, first_dt = first
        current_week = self.week_start_utc(datetime.now(timezone.utc))
        first_week = self.week_start_utc(first_dt)
        if first_week == current_week:
            return {"ok": True, "rotated": False, "reason": "current week only"}

        last_week_start = current_week - timedelta(days=7)
        last_week_end = current_week - timedelta(seconds=1)

        old_lines: List[str] = []
        keep_lines: List[str] = []
        invalid_json_lines = 0
        invalid_ts = 0

        with journal_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                if not raw_line.strip():
                    continue
                try:
                    rec = json.loads(raw_line)
                except json.JSONDecodeError:
                    invalid_json_lines += 1
                    keep_lines.append(raw_line)
                    continue
                if not isinstance(rec, dict):
                    invalid_json_lines += 1
                    keep_lines.append(raw_line)
                    continue
                ts_value = rec.get("ts")
                if not isinstance(ts_value, str):
                    invalid_ts += 1
                    keep_lines.append(raw_line)
                    continue
                parsed = self.parse_iso_ts(ts_value)
                if parsed is None:
                    invalid_ts += 1
                    keep_lines.append(raw_line)
                    continue
                serialized = json.dumps(rec, ensure_ascii=False) + "\n"
                if last_week_start <= parsed <= last_week_end:
                    old_lines.append(serialized)
                else:
                    keep_lines.append(serialized)

        if not old_lines:
            return {
                "ok": True,
                "rotated": False,
                "reason": "no last-week events",
                "invalid_json_lines": invalid_json_lines,
                "invalid_ts": invalid_ts,
            }

        archive = journal_path.with_name(
            f"journal.{last_week_start:%Y%m%d}-{last_week_end:%Y%m%d}.jsonl"
        )
        self.state_store.write_text(archive, "".join(old_lines))
        self.state_store.write_text(journal_path, "".join(keep_lines))
        return {
            "ok": True,
            "rotated": True,
            "archive": str(archive),
            "archived": len(old_lines),
            "kept": len(keep_lines),
            "invalid_json_lines": invalid_json_lines,
            "invalid_ts": invalid_ts,
        }

    def init_replay_state(self, seed_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        base_state = seed_state if isinstance(seed_state, dict) else {}
        state: Dict[str, Any] = dict(base_state)
        state.setdefault("session_id", "")
        state.setdefault("current_phase", "")
        state.setdefault("current_task", "")
        state.setdefault("last_action", "")
        state.setdefault("next_step", "")
        state.setdefault("verification_status", "")
        state.setdefault("last_commit", "")
        state.setdefault("last_error", "")
        state.setdefault("compact_context", "")
        state.setdefault("task_id", "")
        state.setdefault("task_title", "")
        state.setdefault("task_status", "")
        state.setdefault("plan_steps", [])
        state.setdefault("artifact_summary", "")
        state.setdefault("last_verification", {})
        state.setdefault("failure_reason", "")

        if not isinstance(state.get("task_id"), str):
            state["task_id"] = ""
        if not isinstance(state.get("task_title"), str):
            state["task_title"] = ""
        if not isinstance(state.get("task_status"), str):
            state["task_status"] = ""
        if not isinstance(state.get("plan_steps"), list):
            state["plan_steps"] = []
        if not isinstance(state.get("artifact_summary"), str):
            state["artifact_summary"] = ""
        if not isinstance(state.get("last_verification"), dict):
            state["last_verification"] = {}
        if not isinstance(state.get("failure_reason"), str):
            state["failure_reason"] = ""

        warnings = state.get("replay_warnings")
        if not isinstance(warnings, dict):
            warnings = {"invalid_lines": 0, "dropped_events": 0}
        warnings.setdefault("invalid_lines", 0)
        warnings.setdefault("dropped_events", 0)
        state["replay_warnings"] = warnings

        applied_event_ids = state.get("applied_event_ids")
        if not isinstance(applied_event_ids, list):
            applied_event_ids = []
        state["applied_event_ids"] = applied_event_ids
        return state

    def select_target_session_id(
        self, events: List[Dict[str, Any]], preferred: Optional[str]
    ) -> Optional[str]:
        if preferred:
            return preferred

        latest_session_start_seq = -1
        latest_session_start_id: Optional[str] = None
        latest_any_seq = -1
        latest_any_id: Optional[str] = None

        for event in events:
            seq = event.get("seq")
            session_id = event.get("session_id")
            if not isinstance(seq, int) or not isinstance(session_id, str):
                continue
            if seq > latest_any_seq:
                latest_any_seq = seq
                latest_any_id = session_id
            if event.get("kind") == "session.start" and seq > latest_session_start_seq:
                latest_session_start_seq = seq
                latest_session_start_id = session_id

        return latest_session_start_id or latest_any_id

    def append_applied_event_id(
        self, state: Dict[str, Any], event_id: str, max_size: int = 10000
    ) -> None:
        applied_event_ids = state.get("applied_event_ids")
        if not isinstance(applied_event_ids, list):
            applied_event_ids = []
            state["applied_event_ids"] = applied_event_ids
        applied_event_ids.append(event_id)
        if len(applied_event_ids) > max_size:
            applied_event_ids.pop(0)

    def apply_event_to_state(
        self, state: Dict[str, Any], event: Dict[str, Any]
    ) -> None:
        kind = event.get("kind")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if kind == "session.start":
            session_id = event.get("session_id")
            if isinstance(session_id, str):
                state["session_id"] = session_id
            state["current_phase"] = "session"
            state["last_action"] = "session started"
            return

        if kind == "session.end":
            state["last_action"] = "session ended"
            return

        if kind == "task.start":
            title = (
                payload.get("title")
                if isinstance(payload.get("title"), str)
                else "unknown"
            )
            task_id = payload.get("task_id")
            if isinstance(task_id, str):
                state["task_id"] = task_id
            state["task_title"] = title
            state["task_status"] = "in-progress"
            state["current_task"] = title
            state["current_phase"] = "task"
            state["last_action"] = "task started"
            return

        if kind == "task.update":
            if not state.get("current_task"):
                state["current_task"] = "unknown"
            status = (
                payload.get("status")
                if isinstance(payload.get("status"), str)
                else "task"
            )
            note = (
                payload.get("note")
                if isinstance(payload.get("note"), str)
                else "task updated"
            )
            state["current_phase"] = status
            state["last_action"] = note
            return

        if kind == "task.end":
            if not state.get("current_task"):
                state["current_task"] = "unknown"
            summary = (
                payload.get("summary")
                if isinstance(payload.get("summary"), str)
                else "task ended"
            )
            next_action = (
                payload.get("next_action")
                if isinstance(payload.get("next_action"), str)
                else ""
            )
            state["task_status"] = "done"
            state["last_action"] = summary
            state["next_step"] = next_action
            state["current_task"] = ""
            return

        if kind == "task.created":
            task_id = payload.get("task_id")
            title = payload.get("title")
            status = payload.get("status")
            if isinstance(task_id, str):
                state["task_id"] = task_id
            if isinstance(title, str):
                state["task_title"] = title
                state["current_task"] = title
            if isinstance(status, str):
                state["task_status"] = status
            state["last_action"] = "task created"
            return

        if kind == "task.progress":
            status = payload.get("status")
            note = payload.get("note")
            if isinstance(status, str):
                state["task_status"] = status
                state["current_phase"] = status
            if isinstance(note, str) and note:
                state["last_action"] = note
            else:
                state["last_action"] = "task progress"
            return

        if kind == "task.blocked":
            reason = payload.get("reason")
            note = payload.get("note")
            state["task_status"] = "blocked"
            if isinstance(reason, str) and reason:
                state["failure_reason"] = reason
            if isinstance(note, str) and note:
                state["last_action"] = note
            else:
                state["last_action"] = "task blocked"
            return

        if kind == "plan.start":
            steps = payload.get("steps")
            if isinstance(steps, list):
                state["plan_steps"] = steps
            state["last_action"] = "plan started"
            return

        if kind == "plan.step":
            step = payload.get("step") or payload.get("title")
            if isinstance(step, str):
                if not isinstance(state.get("plan_steps"), list):
                    state["plan_steps"] = []
                state["plan_steps"].append(step)
            state["last_action"] = "plan step recorded"
            return

        if kind == "plan.end":
            state["last_action"] = "plan ended"
            return

        if kind == "artifact.summary":
            summary = payload.get("summary")
            if isinstance(summary, str):
                state["artifact_summary"] = summary
            state["last_action"] = "artifact summarized"
            return

        if kind == "verify.start":
            state["verification_status"] = "running"
            state["last_action"] = "verify started"
            return

        if kind == "verify.end":
            ok = payload.get("ok")
            returncode = payload.get("returncode")
            stdout = payload.get("stdout")
            stderr = payload.get("stderr")
            state["verification_status"] = "passed" if ok else "failed"
            state["last_verification"] = {
                "ok": ok,
                "returncode": returncode if isinstance(returncode, int) else None,
                "stdout": self._truncate_text(stdout, limit=500)
                if isinstance(stdout, str)
                else None,
                "stderr": self._truncate_text(stderr, limit=500)
                if isinstance(stderr, str)
                else None,
            }
            if ok is False:
                if isinstance(stderr, str) and stderr:
                    state["failure_reason"] = stderr
            state["last_action"] = "verify finished"
            return

        if kind == "verify.result":
            ok = payload.get("ok")
            returncode = payload.get("returncode")
            stdout = payload.get("stdout")
            stderr = payload.get("stderr")
            reason = payload.get("reason")
            state["last_verification"] = {
                "ok": ok,
                "returncode": returncode if isinstance(returncode, int) else None,
                "stdout": self._truncate_text(stdout, limit=500)
                if isinstance(stdout, str)
                else None,
                "stderr": self._truncate_text(stderr, limit=500)
                if isinstance(stderr, str)
                else None,
            }
            if ok is False:
                if isinstance(reason, str) and reason:
                    state["failure_reason"] = reason
                elif isinstance(stderr, str) and stderr:
                    state["failure_reason"] = stderr
            state["last_action"] = "verify result recorded"
            return

        if kind == "commit.start":
            message = payload.get("message")
            if isinstance(message, str) and message:
                state["last_commit"] = message
            state["last_action"] = "commit started"
            return

        if kind == "commit.end":
            sha = payload.get("sha")
            summary = payload.get("summary")
            if isinstance(sha, str) and sha:
                state["last_commit"] = sha
            elif isinstance(summary, str) and summary:
                state["last_commit"] = summary
            state["last_action"] = "commit finished"
            return

        if kind == "file.edit":
            action = payload.get("action")
            path = payload.get("path")
            if isinstance(action, str) and isinstance(path, str):
                state["last_action"] = f"file {action}: {path}"
            return

        if kind == "tool.result":
            ok = payload.get("ok")
            if ok is False:
                error = payload.get("error")
                if isinstance(error, str):
                    state["last_error"] = error
            return

        if kind == "error":
            message = payload.get("message")
            if isinstance(message, str):
                state["last_error"] = message
            state["last_action"] = "error recorded"
            return

    def replay_events_to_state(
        self,
        seed_state: Optional[Dict[str, Any]],
        events: List[Dict[str, Any]],
        preferred_session_id: Optional[str] = None,
        invalid_lines: int = 0,
    ) -> Dict[str, Any]:
        state = self.init_replay_state(seed_state)
        if invalid_lines:
            state["replay_warnings"]["invalid_lines"] = invalid_lines

        target_session_id = self.select_target_session_id(events, preferred_session_id)
        if not target_session_id:
            return state

        for event in events:
            session_id = event.get("session_id")
            if session_id != target_session_id:
                continue
            event_id = event.get("event_id")
            if isinstance(event_id, str) and event_id in state["applied_event_ids"]:
                state["replay_warnings"]["dropped_events"] += 1
                continue
            self.apply_event_to_state(state, event)
            if isinstance(event_id, str):
                self.append_applied_event_id(state, event_id)

        if not state.get("session_id"):
            state["session_id"] = target_session_id
        return state
