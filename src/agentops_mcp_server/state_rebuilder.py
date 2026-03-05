from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .repo_context import RepoContext
from .state_store import StateStore


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

    def read_journal_events(
        self,
        start_seq: int,
        end_seq: Optional[int] = None,
        journal_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        if start_seq < 0:
            raise ValueError("start_seq must be >= 0")
        if end_seq is not None and end_seq < start_seq:
            raise ValueError("end_seq must be >= start_seq")

        path = journal_path or self.repo_context.journal
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

    def read_recent_journal_events(
        self,
        max_events: int,
        session_id: Optional[str] = None,
        journal_path: Optional[Path] = None,
    ) -> List[Dict[str, Any]]:
        if max_events <= 0:
            return []
        path = journal_path or self.repo_context.journal
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
            if session_id is not None:
                rec_session = rec.get("session_id")
                if rec_session != session_id:
                    continue
            events.append(rec)
        events.reverse()
        return events

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

    def init_replay_state(
        self, snapshot_state: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        base_state = snapshot_state if isinstance(snapshot_state, dict) else {}
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
        snapshot_state: Optional[Dict[str, Any]],
        events: List[Dict[str, Any]],
        preferred_session_id: Optional[str] = None,
        invalid_lines: int = 0,
    ) -> Dict[str, Any]:
        state = self.init_replay_state(snapshot_state)
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

    def roll_forward_replay(
        self,
        checkpoint_path: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_checkpoint_path = self.resolve_path(
            checkpoint_path, self.repo_context.checkpoint
        )
        checkpoint = self.state_store.read_json_file(resolved_checkpoint_path)
        if checkpoint is None:
            return {
                "ok": False,
                "reason": "checkpoint not found",
                "path": str(resolved_checkpoint_path),
            }

        resolved_snapshot_path = snapshot_path
        if not resolved_snapshot_path:
            snapshot_ref = checkpoint.get("snapshot_path")
            if isinstance(snapshot_ref, str) and snapshot_ref.strip():
                resolved_snapshot_path = snapshot_ref

        resolved_snapshot_file = None
        if resolved_snapshot_path:
            candidate = Path(resolved_snapshot_path)
            if not candidate.is_absolute():
                agent_candidate = self.repo_context.snapshot.parent / candidate
                if agent_candidate.exists():
                    resolved_snapshot_file = agent_candidate
        if resolved_snapshot_file is None:
            resolved_snapshot_file = self.resolve_path(
                resolved_snapshot_path, self.repo_context.snapshot
            )
        snapshot = self.state_store.read_json_file(resolved_snapshot_file)
        if snapshot is None:
            return {
                "ok": False,
                "reason": "snapshot not found",
                "path": str(resolved_snapshot_file),
            }

        if start_seq is None:
            checkpoint_seq = checkpoint.get("last_applied_seq")
            if isinstance(checkpoint_seq, int):
                start_seq = checkpoint_seq
            else:
                snapshot_seq = snapshot.get("last_applied_seq")
                if isinstance(snapshot_seq, int):
                    start_seq = snapshot_seq
                else:
                    start_seq = 0

        journal_result = self.read_journal_events(start_seq=start_seq, end_seq=end_seq)
        return {
            "ok": True,
            "checkpoint": checkpoint,
            "checkpoint_path": str(resolved_checkpoint_path),
            "snapshot": snapshot,
            "snapshot_path": str(resolved_snapshot_file),
            "start_seq": start_seq,
            "end_seq": end_seq,
            "events": journal_result["events"],
            "invalid_lines": journal_result["invalid_lines"],
            "last_seq": journal_result["last_seq"],
            "journal_path": journal_result["path"],
        }

    def continue_state_rebuild(
        self,
        checkpoint_path: Optional[str] = None,
        snapshot_path: Optional[str] = None,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        replay = self.roll_forward_replay(
            checkpoint_path=checkpoint_path,
            snapshot_path=snapshot_path,
            start_seq=start_seq,
            end_seq=end_seq,
        )
        if not replay.get("ok"):
            return replay

        snapshot = replay.get("snapshot") or {}
        snapshot_state = snapshot.get("state") if isinstance(snapshot, dict) else None
        events = replay.get("events") or []
        invalid_lines = (
            replay.get("invalid_lines")
            if isinstance(replay.get("invalid_lines"), int)
            else 0
        )
        state = self.replay_events_to_state(
            snapshot_state=snapshot_state,
            events=events,
            preferred_session_id=session_id,
            invalid_lines=invalid_lines,
        )

        return {
            "ok": True,
            "state": state,
            "last_applied_seq": replay.get("last_seq"),
            "checkpoint_path": replay.get("checkpoint_path"),
            "snapshot_path": replay.get("snapshot_path"),
            "journal_path": replay.get("journal_path"),
            "start_seq": replay.get("start_seq"),
            "end_seq": replay.get("end_seq"),
            "events_applied": len(events),
        }
