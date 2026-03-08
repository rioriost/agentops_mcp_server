from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .git_repo import GitRepo
from .repo_context import RepoContext
from .state_rebuilder import StateRebuilder
from .state_store import StateStore, now_iso


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

    def _load_tx_state(self) -> Dict[str, Any]:
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            return rebuild["state"]
        return {}

    def _active_tx(self) -> Dict[str, Any]:
        state = self._load_tx_state()
        active_tx = state.get("active_tx")
        return active_tx if isinstance(active_tx, dict) else {}

    def _extract_last_error(self, verify_state: Any, commit_state: Any) -> str:
        for source in (verify_state, commit_state):
            if not isinstance(source, dict):
                continue
            last_result = source.get("last_result")
            if isinstance(last_result, dict):
                error = last_result.get("error")
                if isinstance(error, str) and error.strip():
                    return error.strip()
        return ""

    def _extract_last_commit(self, commit_state: Any) -> str:
        if not isinstance(commit_state, dict):
            return ""
        last_result = commit_state.get("last_result")
        if not isinstance(last_result, dict):
            return ""
        for key in ("sha", "summary"):
            value = last_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def ops_compact_context(
        self, max_chars: Optional[int] = None, include_diff: Optional[bool] = None
    ) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 800
        )
        resolved_include_diff = bool(include_diff)

        active_tx = self._active_tx()
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
        last_error = self._extract_last_error(verify_state, commit_state)
        last_commit = self._extract_last_commit(commit_state)
        state_view = {
            "session_id": "",
            "current_phase": active_tx.get("status") or "",
            "current_task": active_tx.get("ticket_id") or "",
            "last_action": active_tx.get("semantic_summary") or "",
            "next_step": active_tx.get("next_action")
            or active_tx.get("current_step")
            or "",
            "verification_status": verify_state.get("status") or "",
            "last_commit": last_commit,
            "last_error": last_error,
        }

        diff_stat = self.git_repo.diff_stat() if resolved_include_diff else None
        summary = build_compact_context(state_view, diff_stat, resolved_max_chars)

        return {
            "ok": True,
            "compact_context": summary,
            "max_chars": resolved_max_chars,
            "include_diff": resolved_include_diff,
        }

    def ops_handoff_export(self) -> Dict[str, Any]:
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            rebuilt_state = rebuild["state"]
            rebuilt_active = (
                rebuilt_state.get("active_tx")
                if isinstance(rebuilt_state.get("active_tx"), dict)
                else {}
            )
            next_action = rebuilt_active.get("next_action")
            current_step = rebuilt_active.get("current_step")
            if not isinstance(next_action, str) or not next_action.strip():
                rebuilt_active["next_action"] = (
                    current_step.strip()
                    if isinstance(current_step, str) and current_step.strip()
                    else "tx.begin"
                )
            self.state_store.tx_state_save(rebuilt_state)
            active_tx = rebuilt_active
        else:
            active_tx = self._active_tx()
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
        last_error = self._extract_last_error(verify_state, commit_state)
        last_commit = self._extract_last_commit(commit_state)
        next_step = (
            active_tx.get("next_action") or active_tx.get("current_step") or "tx.begin"
        )

        handoff = {
            "ts": now_iso(),
            "session_id": "",
            "current_task": active_tx.get("ticket_id") or "",
            "last_action": active_tx.get("semantic_summary") or "",
            "next_step": next_step,
            "verification_status": verify_state.get("status") or "",
            "last_commit": last_commit,
            "last_error": last_error,
            "compact_context": active_tx.get("semantic_summary") or "",
        }

        target = self.repo_context.handoff
        self.state_store.write_text(
            target, json.dumps(handoff, ensure_ascii=False, indent=2) + "\n"
        )
        resolved_path = str(target)

        return {"ok": True, "handoff": handoff, "path": resolved_path, "wrote": True}

    def ops_resume_brief(self, max_chars: Optional[int] = None) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 400
        )
        active_tx = self._active_tx()
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

        lines = ["resume_brief:"]

        def _line(label: str, value: Any) -> None:
            if isinstance(value, str) and value.strip():
                lines.append(f"- {label}: {value.strip()}")

        _line("ticket_id", active_tx.get("ticket_id"))
        _line("status", active_tx.get("status"))
        _line("current_step", active_tx.get("current_step"))
        _line("next_action", active_tx.get("next_action"))
        _line("verify_status", verify_state.get("status"))
        _line("commit_status", commit_state.get("status"))

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
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id is required")
        resolved_session_id = session_id.strip()
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
        event = None

        tx_phase = (
            status.strip()
            if isinstance(status, str) and status.strip()
            else "in-progress"
        )
        tx_step_id = (
            task_id.strip() if isinstance(task_id, str) and task_id.strip() else "task"
        )
        active_tx = self._active_tx()
        active_tx_id = active_tx.get("tx_id")
        resolved_task_id = (
            task_id.strip() if isinstance(task_id, str) and task_id.strip() else ""
        )
        if (
            not isinstance(active_tx_id, str)
            or not active_tx_id.strip()
            or active_tx_id.strip() == "none"
        ):
            if not resolved_task_id:
                raise ValueError("tx.begin required before other events")
            self._emit_tx_event(
                event_type="tx.begin",
                payload={"ticket_id": resolved_task_id, "ticket_title": title.strip()},
                title=resolved_task_id,
                task_id=resolved_task_id,
                phase=tx_phase,
                step_id="none",
                session_id=session_id,
                agent_id=agent_id,
            )
            active_tx = self._active_tx()
            active_tx_id = active_tx.get("tx_id")
        if (
            not isinstance(active_tx_id, str)
            or not active_tx_id.strip()
            or active_tx_id.strip() == "none"
        ):
            raise ValueError("tx.begin required before other events")
        resolved_tx_id = active_tx_id.strip()
        if resolved_task_id and resolved_task_id != resolved_tx_id:
            raise ValueError("tx_id does not match active transaction")
        self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": "task started"},
            title=resolved_tx_id,
            task_id=resolved_tx_id,
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
        event = None

        resolved_task_id = task_id.strip() if isinstance(task_id, str) else ""
        if not resolved_task_id:
            active_tx = self._active_tx()
            active_tx_id = active_tx.get("tx_id")
            if isinstance(active_tx_id, str) and active_tx_id.strip():
                resolved_task_id = active_tx_id.strip()
        if resolved_task_id and "task_id" not in payload:
            payload["task_id"] = resolved_task_id

        resolved_status = status.strip() if isinstance(status, str) else ""
        if resolved_status in {"blocked", "done"}:
            tx_phase = "in-progress"
        else:
            tx_phase = resolved_status or "in-progress"
        tx_step_id = (
            task_id.strip()
            if isinstance(task_id, str) and task_id.strip()
            else (resolved_status if resolved_status else "task")
        )
        description = payload.get("note") or "task updated"
        self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": description},
            title=resolved_task_id or "task",
            task_id=resolved_task_id or None,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )
        if isinstance(user_intent, str) and user_intent.strip():
            self._emit_tx_event(
                event_type="tx.user_intent.set",
                payload={"user_intent": user_intent.strip()},
                title=resolved_task_id or "task",
                task_id=resolved_task_id or None,
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
        event = None

        resolved_task_id = task_id.strip() if isinstance(task_id, str) else ""
        if not resolved_task_id:
            active_tx = self._active_tx()
            active_tx_id = active_tx.get("tx_id")
            if isinstance(active_tx_id, str) and active_tx_id.strip():
                resolved_task_id = active_tx_id.strip()
        if resolved_task_id and "task_id" not in payload:
            payload["task_id"] = resolved_task_id

        tx_phase = (
            status.strip() if isinstance(status, str) and status.strip() else "done"
        )
        tx_step_id = resolved_task_id or "task"
        end_type = "tx.end.blocked" if tx_phase == "blocked" else "tx.end.done"
        end_payload = {"summary": payload.get("summary", "")}
        if isinstance(payload.get("next_action"), str) and payload.get("next_action"):
            end_payload["next_action"] = payload.get("next_action")
        if end_type == "tx.end.blocked":
            end_payload["reason"] = payload.get("summary", "")
        self._emit_tx_event(
            event_type=end_type,
            payload=end_payload,
            title=resolved_task_id or "task",
            task_id=resolved_task_id or None,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        return {"ok": True, "event": event, "payload": payload}

    def ops_capture_state(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if not rebuild.get("ok"):
            return rebuild

        state = rebuild.get("state") or {}
        active_tx = (
            state.get("active_tx") if isinstance(state.get("active_tx"), dict) else {}
        )
        next_action = active_tx.get("next_action")
        current_step = active_tx.get("current_step")
        if not isinstance(next_action, str) or not next_action.strip():
            active_tx["next_action"] = (
                current_step.strip()
                if isinstance(current_step, str) and current_step.strip()
                else "tx.begin"
            )
        save_result = self.state_store.tx_state_save(state)
        last_seq = state.get("last_applied_seq")
        last_seq_value = last_seq if isinstance(last_seq, int) else 0

        return {
            "ok": True,
            "state": save_result,
            "last_applied_seq": last_seq_value,
        }

    def ops_task_summary(
        self, session_id: Optional[str] = None, max_chars: Optional[int] = None
    ) -> Dict[str, Any]:
        resolved_max_chars = (
            max_chars if isinstance(max_chars, int) and max_chars > 0 else 400
        )
        active_tx = self._active_tx()
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
        last_error = self._extract_last_error(verify_state, commit_state)
        last_verification = (
            verify_state.get("last_result") if isinstance(verify_state, dict) else {}
        )
        summary = {
            "session_id": "",
            "task_id": active_tx.get("ticket_id") or "",
            "task_title": "",
            "task_status": active_tx.get("status") or "",
            "current_task": active_tx.get("ticket_id") or "",
            "last_action": active_tx.get("semantic_summary") or "",
            "next_step": active_tx.get("next_action")
            or active_tx.get("current_step")
            or "",
            "plan_steps": [],
            "artifact_summary": "",
            "failure_reason": last_error,
            "verification_status": verify_state.get("status") or "",
            "last_verification": last_verification
            if isinstance(last_verification, dict)
            else {},
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

        recent_events = self.state_rebuilder.read_recent_tx_events(resolved_max_events)

        active_tx = self._active_tx()
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
        resolved_session_id = session_id if isinstance(session_id, str) else ""
        last_error = self._extract_last_error(verify_state, commit_state)

        event_summaries = []
        for event in recent_events:
            event_summaries.append(
                {
                    "seq": event.get("seq"),
                    "ts": event.get("ts"),
                    "event_type": event.get("event_type"),
                    "session_id": event.get("session_id"),
                }
            )

        artifacts = []
        summary = {
            "ts": now_iso(),
            "session_id": resolved_session_id,
            "recent_events": event_summaries,
            "failure_reason": last_error,
            "last_error": last_error,
            "verification_status": verify_state.get("status") or "",
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
                event_type = event.get("event_type")
                ts = event.get("ts")
                label = f"- {seq} {event_type}"
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

        return {
            "ok": True,
            "summary": summary,
            "text": text,
            "path": str(resolved_path),
            "text_path": str(text_path),
            "max_events": resolved_max_events,
            "max_chars": resolved_max_chars,
        }
