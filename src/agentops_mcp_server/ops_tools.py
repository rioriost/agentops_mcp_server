from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .git_repo import GitRepo
from .repo_context import RepoContext
from .state_rebuilder import StateRebuilder
from .state_store import StateStore, now_iso
from .test_suggestions import extract_artifact_paths


def truncate_text(value: Optional[str], limit: int = 2000) -> Optional[str]:
    if value is None:
        return None
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    suffix = "...(truncated)"
    prefix = value[:limit].rstrip()
    return prefix + suffix


def build_compact_context(
    state: Dict[str, Any],
    diff_stat: Optional[str],
    max_chars: int,
) -> str:
    lines: List[str] = []

    def _add(label: str, value: Any) -> None:
        if isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}")

    _add("session_id", state.get("session_id"))
    _add("current_phase", state.get("current_phase"))
    _add("current_task", state.get("current_task"))
    _add("last_action", state.get("last_action"))
    _add("next_step", state.get("next_step"))
    _add("verification_status", state.get("verification_status"))
    _add("last_commit", state.get("last_commit"))
    _add("last_error", state.get("last_error"))

    if diff_stat and diff_stat.strip():
        lines.append("diff_stat:")
        lines.append(diff_stat.strip())

    summary = "\n".join(lines).strip()
    if not summary:
        summary = "no recent state available"
    return truncate_text(summary, limit=max_chars) or ""


def sanitize_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not args:
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            sanitized[key] = truncate_text(value)
        else:
            sanitized[key] = value
    return sanitized


def summarize_result(result: Any, limit: int = 2000) -> Any:
    try:
        text = json.dumps(result, ensure_ascii=False)
    except TypeError:
        text = str(result)
    if len(text) <= limit:
        return result
    return {"summary": text[:limit].rstrip() + "...(truncated)", "truncated": True}


class OpsTools:
    def __init__(
        self,
        repo_context: RepoContext,
        state_store: StateStore,
        state_rebuilder: StateRebuilder,
        git_repo: GitRepo,
    ) -> None:
        self.repo_context = repo_context
        self.state_store = state_store
        self.state_rebuilder = state_rebuilder
        self.git_repo = git_repo

    def ops_compact_context(
        self, max_chars: Optional[int] = None, include_diff: Optional[bool] = None
    ) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 800
        )
        resolved_include_diff = bool(include_diff)

        replay = self.state_rebuilder.continue_state_rebuild()
        if replay.get("ok"):
            state = replay.get("state") or {}
            last_seq = replay.get("last_applied_seq")
        else:
            state = self.state_rebuilder.init_replay_state(None)
            last_seq = None

        diff_stat = self.git_repo.diff_stat() if resolved_include_diff else None
        summary = build_compact_context(state, diff_stat, resolved_max_chars)

        state["compact_context"] = summary
        session_id = (
            state.get("session_id")
            if isinstance(state.get("session_id"), str)
            else None
        )
        last_seq_value = last_seq if isinstance(last_seq, int) else None
        self.state_store.snapshot_save(
            state=state, session_id=session_id, last_applied_seq=last_seq_value
        )
        self.state_store.journal_safe(
            "context.compact",
            {
                "length": len(summary),
                "max_chars": resolved_max_chars,
                "include_diff": resolved_include_diff,
            },
        )

        return {
            "ok": True,
            "compact_context": summary,
            "max_chars": resolved_max_chars,
            "include_diff": resolved_include_diff,
        }

    def ops_handoff_export(self) -> Dict[str, Any]:
        replay = self.state_rebuilder.continue_state_rebuild()
        if replay.get("ok"):
            state = replay.get("state") or {}
        else:
            state = self.state_rebuilder.init_replay_state(None)

        handoff = {
            "ts": now_iso(),
            "session_id": state.get("session_id") or "",
            "current_task": state.get("current_task") or "",
            "last_action": state.get("last_action") or "",
            "next_step": state.get("next_step") or "",
            "verification_status": state.get("verification_status") or "",
            "last_commit": state.get("last_commit") or "",
            "last_error": state.get("last_error") or "",
            "compact_context": state.get("compact_context") or "",
        }

        target = self.repo_context.handoff
        self.state_store.write_text(
            target, json.dumps(handoff, ensure_ascii=False, indent=2) + "\n"
        )
        resolved_path = str(target)
        self.state_store.journal_safe(
            "session.handoff",
            {"path": resolved_path, "wrote": True, "fields": list(handoff.keys())},
        )

        return {"ok": True, "handoff": handoff, "path": resolved_path, "wrote": True}

    def ops_resume_brief(self, max_chars: Optional[int] = None) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 400
        )
        replay = self.state_rebuilder.continue_state_rebuild()
        if replay.get("ok"):
            state = replay.get("state") or {}
        else:
            state = self.state_rebuilder.init_replay_state(None)

        lines = ["resume_brief:"]

        def _line(label: str, key: str) -> None:
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")

        _line("session_id", "session_id")
        _line("current_task", "current_task")
        _line("last_action", "last_action")
        _line("next_step", "next_step")
        _line("verification_status", "verification_status")
        _line("last_commit", "last_commit")
        _line("last_error", "last_error")

        brief = "\n".join(lines).strip()
        brief = truncate_text(brief, limit=resolved_max_chars) or ""
        if len(brief) > resolved_max_chars:
            brief = brief[:resolved_max_chars].rstrip()

        return {"ok": True, "brief": brief, "max_chars": resolved_max_chars}

    def _emit_tx_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        title: str,
        task_id: Optional[str],
        phase: str,
        step_id: str,
        session_id: Optional[str],
        agent_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        resolved_title = title.strip() if isinstance(title, str) else ""
        resolved_task_id = task_id.strip() if isinstance(task_id, str) else ""
        tx_id = resolved_task_id or resolved_title
        if not tx_id:
            return None
        ticket_id = tx_id
        resolved_session_id = (
            session_id.strip()
            if isinstance(session_id, str) and session_id.strip()
            else "unknown"
        )
        actor: Dict[str, Any] = {"tool": "ops_tools"}
        if isinstance(agent_id, str) and agent_id.strip():
            actor["agent_id"] = agent_id.strip()

        event = self.state_store.tx_event_append(
            tx_id=tx_id,
            ticket_id=ticket_id,
            event_type=event_type,
            phase=phase,
            step_id=step_id,
            actor=actor,
            session_id=resolved_session_id,
            payload=payload,
        )
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            self.state_store.tx_state_save(rebuild["state"])
        return event

    def ops_start_task(
        self,
        title: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title is required")
        payload: Dict[str, Any] = {"title": title.strip()}
        if isinstance(task_id, str) and task_id.strip():
            payload["task_id"] = task_id.strip()
        if isinstance(status, str) and status.strip():
            payload["status"] = status.strip()
        event = self.state_store.journal_append(
            kind="task.start",
            payload=payload,
            session_id=session_id,
            agent_id=agent_id,
        )

        tx_phase = (
            status.strip()
            if isinstance(status, str) and status.strip()
            else "in-progress"
        )
        tx_step_id = (
            task_id.strip() if isinstance(task_id, str) and task_id.strip() else "task"
        )
        self._emit_tx_event(
            event_type="tx.begin",
            payload={"ticket_id": task_id or title, "ticket_title": title.strip()},
            title=title,
            task_id=task_id,
            phase=tx_phase,
            step_id="none",
            session_id=session_id,
            agent_id=agent_id,
        )
        self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": "task started"},
            title=title,
            task_id=task_id,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        return {"ok": True, "event": event, "payload": payload}

    def ops_update_task(
        self,
        status: Optional[str] = None,
        note: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if isinstance(status, str) and status.strip():
            payload["status"] = status.strip()
        if isinstance(note, str) and note.strip():
            payload["note"] = note.strip()
        if isinstance(task_id, str) and task_id.strip():
            payload["task_id"] = task_id.strip()
        if not payload:
            raise ValueError("status or note is required")
        event = self.state_store.journal_append(
            kind="task.update",
            payload=payload,
            session_id=session_id,
            agent_id=agent_id,
        )

        tx_phase = (
            status.strip()
            if isinstance(status, str) and status.strip()
            else "in-progress"
        )
        tx_step_id = (
            task_id.strip()
            if isinstance(task_id, str) and task_id.strip()
            else (
                status.strip() if isinstance(status, str) and status.strip() else "task"
            )
        )
        description = payload.get("note") or "task updated"
        self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": description},
            title=task_id or "task",
            task_id=task_id,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )
        if isinstance(user_intent, str) and user_intent.strip():
            self._emit_tx_event(
                event_type="tx.user_intent.set",
                payload={"user_intent": user_intent.strip()},
                title=task_id or "task",
                task_id=task_id,
                phase=tx_phase,
                step_id=tx_step_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        return {"ok": True, "event": event, "payload": payload}

    def ops_end_task(
        self,
        summary: str,
        next_action: Optional[str] = None,
        status: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary is required")
        payload: Dict[str, Any] = {"summary": summary.strip()}
        if isinstance(next_action, str) and next_action.strip():
            payload["next_action"] = next_action.strip()
        if isinstance(status, str) and status.strip():
            payload["status"] = status.strip()
        if isinstance(task_id, str) and task_id.strip():
            payload["task_id"] = task_id.strip()
        event = self.state_store.journal_append(
            kind="task.end",
            payload=payload,
            session_id=session_id,
            agent_id=agent_id,
        )

        tx_phase = (
            status.strip() if isinstance(status, str) and status.strip() else "done"
        )
        tx_step_id = (
            task_id.strip() if isinstance(task_id, str) and task_id.strip() else "task"
        )
        end_type = "tx.end.blocked" if tx_phase == "blocked" else "tx.end.done"
        end_payload = {"summary": payload.get("summary", "")}
        if isinstance(payload.get("next_action"), str) and payload.get("next_action"):
            end_payload["next_action"] = payload.get("next_action")
        if end_type == "tx.end.blocked":
            end_payload["reason"] = payload.get("summary", "")
        self._emit_tx_event(
            event_type=end_type,
            payload=end_payload,
            title=task_id or "task",
            task_id=task_id,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        return {"ok": True, "event": event, "payload": payload}

    def ops_capture_state(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        replay = self.state_rebuilder.continue_state_rebuild(session_id=session_id)
        if not replay.get("ok"):
            return replay

        state = replay.get("state") or {}
        last_seq = replay.get("last_applied_seq")
        last_seq_value = last_seq if isinstance(last_seq, int) else 0

        resolved_session_id = session_id
        if not resolved_session_id and isinstance(state.get("session_id"), str):
            resolved_session_id = state.get("session_id")

        snapshot_result = self.state_store.snapshot_save(
            state=state, session_id=resolved_session_id, last_applied_seq=last_seq_value
        )
        checkpoint_result = self.state_store.checkpoint_update(
            last_applied_seq=last_seq_value,
            snapshot_path=self.repo_context.snapshot.name,
        )
        self.state_store.journal_safe(
            "state.capture",
            {"session_id": resolved_session_id, "last_applied_seq": last_seq_value},
        )

        return {
            "ok": True,
            "snapshot": snapshot_result,
            "checkpoint": checkpoint_result,
            "last_applied_seq": last_seq_value,
        }

    def ops_task_summary(
        self, session_id: Optional[str] = None, max_chars: Optional[int] = None
    ) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 400
        )
        replay = self.state_rebuilder.continue_state_rebuild(session_id=session_id)
        if not replay.get("ok"):
            return replay

        state = replay.get("state") or {}
        summary = {
            "session_id": state.get("session_id") or "",
            "task_id": state.get("task_id") or "",
            "task_title": state.get("task_title") or "",
            "task_status": state.get("task_status") or "",
            "current_task": state.get("current_task") or "",
            "last_action": state.get("last_action") or "",
            "next_step": state.get("next_step") or "",
            "plan_steps": state.get("plan_steps") or [],
            "artifact_summary": state.get("artifact_summary") or "",
            "failure_reason": state.get("failure_reason") or "",
            "verification_status": state.get("verification_status") or "",
            "last_verification": state.get("last_verification") or {},
        }

        lines = ["task_summary:"]

        def _line(label: str, value: Any) -> None:
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")

        _line("task_title", summary["task_title"])
        _line("task_status", summary["task_status"])
        _line("last_action", summary["last_action"])
        _line("next_step", summary["next_step"])
        _line("artifact_summary", summary["artifact_summary"])
        _line("failure_reason", summary["failure_reason"])

        text = "\n".join(lines).strip()
        text = truncate_text(text, limit=resolved_max_chars) or ""
        if len(text) > resolved_max_chars:
            text = text[:resolved_max_chars].rstrip()

        self.state_store.journal_safe(
            "task.summary",
            {
                "session_id": summary["session_id"],
                "task_id": summary["task_id"],
                "task_status": summary["task_status"],
                "length": len(text),
            },
        )

        return {
            "ok": True,
            "summary": summary,
            "text": text,
            "max_chars": resolved_max_chars,
        }

    def ops_observability_summary(
        self,
        session_id: Optional[str] = None,
        max_events: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_max_events = (
            max_events if isinstance(max_events, int) and max_events > 0 else 20
        )
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 800
        )

        recent_events = self.state_rebuilder.read_recent_journal_events(
            resolved_max_events, session_id=session_id
        )

        replay = self.state_rebuilder.continue_state_rebuild(session_id=session_id)
        if replay.get("ok"):
            state = replay.get("state") or {}
        else:
            state = self.state_rebuilder.init_replay_state(None)

        resolved_session_id = (
            session_id if isinstance(session_id, str) else state.get("session_id") or ""
        )

        event_summaries = []
        for event in recent_events:
            event_summaries.append(
                {
                    "seq": event.get("seq"),
                    "ts": event.get("ts"),
                    "kind": event.get("kind"),
                    "session_id": event.get("session_id"),
                }
            )

        artifacts = extract_artifact_paths(recent_events)
        summary = {
            "ts": now_iso(),
            "session_id": resolved_session_id,
            "recent_events": event_summaries,
            "failure_reason": state.get("failure_reason") or "",
            "last_error": state.get("last_error") or "",
            "verification_status": state.get("verification_status") or "",
            "artifacts": artifacts,
        }

        resolved_path = self.repo_context.observability
        if resolved_path.suffix:
            text_path = resolved_path.with_suffix(".txt")
        else:
            text_path = Path(str(resolved_path) + ".txt")

        self.state_store.write_text(
            resolved_path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        )

        lines = ["observability_summary:"]
        if event_summaries:
            lines.append("recent_events:")
            for event in event_summaries:
                seq = event.get("seq")
                kind = event.get("kind")
                ts = event.get("ts")
                label = f"- {seq} {kind}"
                if isinstance(ts, str) and ts:
                    label = f"{label} @ {ts}"
                lines.append(label)
        if summary["failure_reason"]:
            lines.append(f"- failure_reason: {summary['failure_reason']}")
        if summary["last_error"]:
            lines.append(f"- last_error: {summary['last_error']}")
        if artifacts:
            lines.append("artifacts:")
            for artifact in artifacts:
                lines.append(f"- {artifact}")

        text = truncate_text("\n".join(lines).strip(), limit=resolved_max_chars) or ""
        self.state_store.write_text(text_path, text + "\n")

        self.state_store.journal_safe(
            "observability.summary",
            {
                "session_id": resolved_session_id,
                "events": len(event_summaries),
                "artifacts": len(artifacts),
                "path": str(resolved_path),
                "text_path": str(text_path),
                "length": len(text),
            },
        )

        return {
            "ok": True,
            "summary": summary,
            "text": text,
            "path": str(resolved_path),
            "text_path": str(text_path),
            "max_events": resolved_max_events,
            "max_chars": resolved_max_chars,
        }
