from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .repo_context import RepoContext


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, repo_context: RepoContext) -> None:
        self.repo_context = repo_context

    def ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_text(self, path: Path, content: str) -> None:
        self.ensure_parent(path)
        path.write_text(content, encoding="utf-8")

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

    def next_journal_seq(self) -> int:
        last = self.read_last_json_line(self.repo_context.journal)
        if isinstance(last, dict):
            seq = last.get("seq")
            if isinstance(seq, int) and seq >= 0:
                return seq + 1
        return 1

    def journal_append(
        self,
        kind: str,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not kind:
            raise ValueError("kind is required")
        seq = self.next_journal_seq()
        resolved_event_id = event_id or str(uuid.uuid4())
        rec: Dict[str, Any] = {
            "seq": seq,
            "event_id": resolved_event_id,
            "ts": now_iso(),
            "project_root": str(self.repo_context.get_repo_root()),
            "kind": kind,
            "payload": payload,
        }
        if session_id is not None:
            rec["session_id"] = session_id
        if agent_id is not None:
            rec["agent_id"] = agent_id
        self.ensure_parent(self.repo_context.journal)
        with self.repo_context.journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {"ok": True, "seq": seq, "event_id": resolved_event_id}

    def _require_str(self, value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

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
        if not isinstance(state.get("schema_version"), str):
            raise ValueError("schema_version is required")
        if not isinstance(state.get("last_applied_seq"), int):
            raise ValueError("last_applied_seq is required")

        active_tx = state.get("active_tx")
        if not isinstance(active_tx, dict):
            raise ValueError("active_tx is required")
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
        next_state = dict(state)
        next_state["last_applied_seq"] = event_result["seq"]
        self.tx_state_save(next_state)
        return {
            "ok": True,
            "seq": event_result["seq"],
            "event_id": event_result["event_id"],
            "path": str(self.repo_context.tx_state),
        }

    def journal_safe(self, kind: str, payload: Dict[str, Any]) -> None:
        try:
            self.journal_append(kind=kind, payload=payload)
        except Exception:  # noqa: BLE001
            return

    def snapshot_save(
        self,
        state: Dict[str, Any],
        session_id: Optional[str] = None,
        last_applied_seq: Optional[int] = None,
        snapshot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if state is None:
            raise ValueError("state is required")
        resolved_snapshot_id = snapshot_id or str(uuid.uuid4())
        snapshot: Dict[str, Any] = {
            "snapshot_id": resolved_snapshot_id,
            "ts": now_iso(),
            "project_root": str(self.repo_context.get_repo_root()),
            "state": state,
        }
        if session_id is not None:
            snapshot["session_id"] = session_id
        if last_applied_seq is not None:
            snapshot["last_applied_seq"] = last_applied_seq
        self.write_text(
            self.repo_context.snapshot,
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
        return {
            "ok": True,
            "path": str(self.repo_context.snapshot),
            "snapshot_id": resolved_snapshot_id,
        }

    def snapshot_load(self) -> Dict[str, Any]:
        snapshot = self.read_json_file(self.repo_context.snapshot)
        if snapshot is None:
            return {
                "ok": False,
                "reason": "snapshot not found",
                "path": str(self.repo_context.snapshot),
            }
        return {
            "ok": True,
            "snapshot": snapshot,
            "path": str(self.repo_context.snapshot),
        }

    def checkpoint_update(
        self,
        last_applied_seq: int,
        snapshot_path: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if last_applied_seq is None:
            raise ValueError("last_applied_seq is required")
        resolved_checkpoint_id = checkpoint_id or str(uuid.uuid4())
        snapshot_ref = snapshot_path or self.repo_context.snapshot.name
        checkpoint: Dict[str, Any] = {
            "checkpoint_id": resolved_checkpoint_id,
            "ts": now_iso(),
            "project_root": str(self.repo_context.get_repo_root()),
            "last_applied_seq": last_applied_seq,
            "snapshot_path": snapshot_ref,
        }
        self.write_text(
            self.repo_context.checkpoint,
            json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
        )
        return {
            "ok": True,
            "path": str(self.repo_context.checkpoint),
            "checkpoint_id": resolved_checkpoint_id,
        }

    def checkpoint_read(self) -> Dict[str, Any]:
        checkpoint = self.read_json_file(self.repo_context.checkpoint)
        if checkpoint is None:
            return {
                "ok": False,
                "reason": "checkpoint not found",
                "path": str(self.repo_context.checkpoint),
            }
        return {
            "ok": True,
            "checkpoint": checkpoint,
            "path": str(self.repo_context.checkpoint),
        }
