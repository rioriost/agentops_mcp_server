from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .git_repo import GitRepo
from .repo_context import RepoContext
from .state_rebuilder import StateRebuilder
from .state_store import StateStore, now_iso
from .workflow_response import (
    build_failure_response,
    build_success_response,
    derive_workflow_guidance,
)


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
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if isinstance(tx_state, dict):
            return tx_state
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            state = rebuild["state"]
            integrity = (
                state.get("integrity")
                if isinstance(state.get("integrity"), dict)
                else {}
            )
            if integrity.get("drift_detected") is True:
                return {}
            return state
        return {}

    def _active_tx(self) -> Dict[str, Any]:
        state = self._load_tx_state()
        active_tx = state.get("active_tx")
        return active_tx if isinstance(active_tx, dict) else {}

    def _materialized_active_tx(self) -> Dict[str, Any]:
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if not isinstance(tx_state, dict):
            return {}
        active_tx = tx_state.get("active_tx")
        return active_tx if isinstance(active_tx, dict) else {}

    def _parse_iso_datetime(self, value: Any) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _debug_start_time(self) -> Optional[datetime]:
        payload = self.state_store.read_json_file(
            self.repo_context.get_repo_root() / ".agent" / "debug_start_time.json"
        )
        if not isinstance(payload, dict):
            return None
        return self._parse_iso_datetime(payload.get("debug_start_time"))

    def _iter_candidate_session_ids_from_agent_artifact(
        self, path: Path, debug_start_time: Optional[datetime]
    ) -> List[str]:
        if not path.exists() or not path.is_file():
            return []

        candidates: List[str] = []
        seen: set[str] = set()

        def _collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key == "session_id" and isinstance(nested, str):
                        cleaned = nested.strip()
                        if cleaned and cleaned not in seen:
                            seen.add(cleaned)
                            candidates.append(cleaned)
                    else:
                        _collect(nested)
            elif isinstance(value, list):
                for item in value:
                    _collect(item)

        try:
            if path.suffix == ".jsonl":
                for raw_line in path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if debug_start_time is not None:
                        ts = self._parse_iso_datetime(record.get("ts"))
                        if ts is None or ts < debug_start_time:
                            continue
                    _collect(record)
                return candidates

            payload = self.state_store.read_json_file(path)
            if not isinstance(payload, dict):
                return []
            if debug_start_time is not None:
                ts = self._parse_iso_datetime(payload.get("ts"))
                updated_at = self._parse_iso_datetime(payload.get("updated_at"))
                effective_ts = updated_at or ts
                if effective_ts is not None and effective_ts < debug_start_time:
                    return []
            _collect(payload)
            return candidates
        except OSError:
            return []

    def _recover_session_id_from_agent_artifacts(
        self, active_tx: Dict[str, Any]
    ) -> str:
        active_tx_id = self._normalize_tx_identifier(active_tx.get("tx_id"))
        active_ticket_id = self._normalize_tx_identifier(active_tx.get("ticket_id"))
        debug_start_time = self._debug_start_time()
        agent_dir = self.repo_context.get_repo_root() / ".agent"

        candidate_paths = [
            self.repo_context.tx_state,
            self.repo_context.tx_event_log,
            self.repo_context.errors,
            self.repo_context.handoff,
            self.repo_context.observability,
        ]

        for path in sorted(agent_dir.glob("*")):
            if path in candidate_paths:
                continue
            if path.name == "debug_start_time.json":
                continue
            if path.is_file():
                candidate_paths.append(path)

        matching_candidates: List[str] = []
        fallback_candidates: List[str] = []
        matching_seen: set[str] = set()
        fallback_seen: set[str] = set()

        def _append_unique(target: List[str], seen: set[str], value: str) -> None:
            if value and value not in seen:
                seen.add(value)
                target.append(value)

        materialized_active_tx = self._materialized_active_tx()
        materialized_tx_id = self._normalize_tx_identifier(
            materialized_active_tx.get("tx_id")
        )
        materialized_ticket_id = self._normalize_tx_identifier(
            materialized_active_tx.get("ticket_id")
        )
        match_tx_id = materialized_tx_id or active_tx_id

        def _record_matches_active_tx(record: Dict[str, Any]) -> bool:
            record_tx_id = self._normalize_tx_identifier(record.get("tx_id"))
            return bool(match_tx_id) and record_tx_id == match_tx_id

        try:
            for raw_line in self.repo_context.tx_event_log.read_text(
                encoding="utf-8"
            ).splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if debug_start_time is not None:
                    ts = self._parse_iso_datetime(record.get("ts"))
                    if ts is None or ts < debug_start_time:
                        continue
                record_session_id = record.get("session_id")
                if not (
                    isinstance(record_session_id, str) and record_session_id.strip()
                ):
                    continue
                if _record_matches_active_tx(record):
                    _append_unique(
                        matching_candidates,
                        matching_seen,
                        record_session_id.strip(),
                    )
        except OSError:
            pass

        if len(matching_candidates) == 1:
            return matching_candidates[0]
        if len(matching_candidates) > 1:
            raise ValueError(
                "session_id is required; unable to recover a unique prior session_id "
                "from .agent artifacts after debug_start_time"
            )

        for path in candidate_paths:
            if path == self.repo_context.tx_event_log:
                continue
            sessions = self._iter_candidate_session_ids_from_agent_artifact(
                path, debug_start_time
            )
            if not sessions:
                continue
            for session_id in sessions:
                _append_unique(fallback_candidates, fallback_seen, session_id)

        if len(fallback_candidates) == 1:
            return fallback_candidates[0]
        raise ValueError(
            "session_id is required; unable to recover prior session_id from .agent "
            "artifacts after debug_start_time"
        )

    def _resolve_session_id(
        self,
        session_id: Optional[str],
        active_tx: Optional[Dict[str, Any]] = None,
        *,
        allow_recovery: bool = True,
    ) -> str:
        resolved_session_id = (
            session_id.strip()
            if isinstance(session_id, str) and session_id.strip()
            else ""
        )
        if resolved_session_id:
            return resolved_session_id

        candidate_active_tx = active_tx if isinstance(active_tx, dict) else None
        if candidate_active_tx is None:
            candidate_active_tx = self._active_tx()

        if allow_recovery:
            try:
                return self._recover_session_id_from_agent_artifacts(
                    candidate_active_tx
                )
            except ValueError:
                pass

        materialized_session_id = candidate_active_tx.get("session_id")
        if isinstance(materialized_session_id, str) and materialized_session_id.strip():
            return materialized_session_id.strip()

        return ""

    def _workflow_success_response(
        self,
        *,
        payload: Optional[Dict[str, Any]] = None,
        event: Optional[Dict[str, Any]] = None,
        tx_state: Optional[Dict[str, Any]] = None,
        **guidance_overrides: Any,
    ) -> Dict[str, Any]:
        resolved_state = (
            tx_state if isinstance(tx_state, dict) else self._load_tx_state()
        )
        response = build_success_response(
            tx_state=resolved_state,
            payload=payload,
            event=event,
            **guidance_overrides,
        )
        if not response.get("canonical_status") and not response.get("next_action"):
            baseline_state = resolved_state if isinstance(resolved_state, dict) else {}
            if not baseline_state:
                baseline_state = {
                    "active_tx": None,
                    "status": None,
                    "next_action": "tx.begin",
                    "verify_state": None,
                    "commit_state": None,
                    "semantic_summary": None,
                    "integrity": {},
                }
            guidance = derive_workflow_guidance(
                baseline_state,
                **guidance_overrides,
            )
            response.update(guidance)
            response["tx_status"] = guidance["canonical_status"]
            response["tx_phase"] = guidance["canonical_phase"]
            response["canonical_status"] = guidance["canonical_status"]
            response["canonical_phase"] = guidance["canonical_phase"]
            response["next_action"] = guidance["next_action"]
            response["terminal"] = guidance["terminal"]
            response["requires_followup"] = guidance["requires_followup"]
            response["followup_tool"] = guidance["followup_tool"]
            response["can_start_new_ticket"] = guidance["can_start_new_ticket"]
            response["resume_required"] = guidance["resume_required"]

        active_tx = (
            resolved_state.get("active_tx")
            if isinstance(resolved_state.get("active_tx"), dict)
            else {}
        )
        verify_state = (
            resolved_state.get("verify_state")
            if isinstance(resolved_state.get("verify_state"), dict)
            else {}
        )
        commit_state = (
            resolved_state.get("commit_state")
            if isinstance(resolved_state.get("commit_state"), dict)
            else {}
        )
        integrity = (
            resolved_state.get("integrity")
            if isinstance(resolved_state.get("integrity"), dict)
            else {}
        )

        response["active_tx"] = active_tx if active_tx else None
        response["active_tx_id"] = active_tx.get("tx_id") if active_tx else None
        response["active_ticket_id"] = active_tx.get("ticket_id") if active_tx else None
        response["current_step"] = None
        response["verify_status"] = verify_state.get("status")
        response["commit_status"] = commit_state.get("status")
        response["integrity_status"] = (
            "blocked" if integrity.get("drift_detected") is True else "healthy"
        )

        return response

    def _canonical_begin_conflict(
        self, requested_task_id: Optional[str]
    ) -> Optional[ValueError]:
        requested_id = self._normalize_tx_identifier(requested_task_id)
        if not requested_id:
            return None

        rebuilt_state: Dict[str, Any] = {}
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            rebuilt_state = rebuild["state"]

        rebuilt_active_tx = (
            rebuilt_state.get("active_tx")
            if isinstance(rebuilt_state.get("active_tx"), dict)
            else {}
        )
        integrity = (
            rebuilt_state.get("integrity")
            if isinstance(rebuilt_state.get("integrity"), dict)
            else {}
        )
        if integrity.get("drift_detected") is True:
            return ValueError(
                "cannot start task because canonical transaction history has integrity drift; "
                "repair or resume the canonical active transaction before emitting tx.begin"
            )

        rebuilt_tx_id = self._normalize_tx_identifier(rebuilt_active_tx.get("tx_id"))
        if (
            rebuilt_tx_id
            and rebuilt_active_tx
            and not self._is_terminal_active_tx(rebuilt_active_tx)
        ):
            if requested_id == rebuilt_tx_id:
                return ValueError(
                    "cannot emit tx.begin for an already-active non-terminal transaction; "
                    "resume it with task update semantics instead"
                )

        materialized_active_tx = self._materialized_active_tx()
        if not materialized_active_tx:
            return None
        if self._is_terminal_active_tx(materialized_active_tx):
            rebuilt_tx_id = self._normalize_tx_identifier(
                rebuilt_active_tx.get("tx_id")
            )
            if rebuilt_tx_id:
                if requested_id == rebuilt_tx_id:
                    return self._active_tx_mismatch_error(
                        requested_task_id, rebuilt_active_tx
                    )
            return None

        materialized_tx_id = self._normalize_tx_identifier(
            materialized_active_tx.get("tx_id")
        )

        if not materialized_tx_id:
            return None
        if requested_id == materialized_tx_id:
            return ValueError(
                "cannot emit tx.begin for an already-active non-terminal transaction; "
                "resume it with task update semantics instead"
            )

        return None

    def _normalize_tx_identifier(self, value: Any) -> str:
        if isinstance(value, bool):
            return ""
        if isinstance(value, int):
            return str(value)
        if not isinstance(value, str):
            return ""
        normalized = value.strip()
        if not normalized or normalized == "none":
            return ""
        return normalized

    def _is_terminal_active_tx(self, active_tx: Dict[str, Any]) -> bool:
        tx_state = self._load_tx_state()
        status = tx_state.get("status") if isinstance(tx_state, dict) else None
        return isinstance(status, str) and status.strip() in {"done", "blocked"}

    def _active_tx_identity(self, active_tx: Dict[str, Any]) -> Dict[str, str]:
        tx_id = self._normalize_tx_identifier(active_tx.get("tx_id"))
        ticket_id = (
            active_tx.get("ticket_id").strip()
            if isinstance(active_tx.get("ticket_id"), str)
            and active_tx.get("ticket_id").strip()
            else ""
        )
        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "canonical_id": tx_id,
            "has_canonical_tx": bool(tx_id),
        }

    def _require_active_tx(
        self, requested_task_id: Optional[str] = None, *, allow_resume: bool = False
    ) -> Tuple[Dict[str, Any], str]:
        active_tx = self._active_tx()
        identity = self._active_tx_identity(active_tx)
        canonical_id = identity["canonical_id"]
        ticket_id = identity["ticket_id"]
        requested_id = self._normalize_tx_identifier(requested_task_id)
        has_canonical_tx = identity["has_canonical_tx"]

        if not has_canonical_tx or not canonical_id:
            raise ValueError("tx.begin required before other events")
        if self._is_terminal_active_tx(active_tx):
            raise ValueError("tx.begin required before other events")

        if requested_id and requested_id == canonical_id:
            return active_tx, canonical_id

        if allow_resume and requested_task_id and requested_task_id == ticket_id:
            return active_tx, canonical_id

        if requested_task_id:
            raise self._active_tx_mismatch_error(requested_task_id, active_tx)

        return active_tx, canonical_id

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

        tx_state = self._load_tx_state()
        active_tx = (
            tx_state.get("active_tx")
            if isinstance(tx_state.get("active_tx"), dict)
            else {}
        )
        verify_state = (
            tx_state.get("verify_state")
            if isinstance(tx_state.get("verify_state"), dict)
            else {}
        )
        commit_state = (
            tx_state.get("commit_state")
            if isinstance(tx_state.get("commit_state"), dict)
            else {}
        )
        last_error = self._extract_last_error(verify_state, commit_state)
        last_commit = self._extract_last_commit(commit_state)
        state_view = {
            "session_id": "",
            "current_phase": tx_state.get("status") or "",
            "current_task": active_tx.get("ticket_id") or "",
            "last_action": tx_state.get("semantic_summary") or "",
            "next_step": tx_state.get("next_action") or "",
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
            state = rebuild["state"]
        else:
            state = self._load_tx_state()

        active_tx = (
            state.get("active_tx") if isinstance(state.get("active_tx"), dict) else {}
        )
        verify_state = (
            state.get("verify_state")
            if isinstance(state.get("verify_state"), dict)
            else {}
        )
        commit_state = (
            state.get("commit_state")
            if isinstance(state.get("commit_state"), dict)
            else {}
        )
        last_error = self._extract_last_error(verify_state, commit_state)
        last_commit = self._extract_last_commit(commit_state)
        next_step = (
            state.get("next_action")
            if isinstance(state.get("next_action"), str) and state.get("next_action")
            else "tx.begin"
        )

        handoff = {
            "ts": now_iso(),
            "session_id": "",
            "current_task": active_tx.get("ticket_id") or "",
            "last_action": state.get("semantic_summary") or "",
            "next_step": next_step,
            "verification_status": verify_state.get("status") or "",
            "last_commit": last_commit,
            "last_error": last_error,
            "compact_context": state.get("semantic_summary") or "",
        }
        if (
            rebuild.get("ok")
            and isinstance(rebuild.get("state"), dict)
            and isinstance(rebuild.get("state", {}).get("integrity"), dict)
            and rebuild["state"]["integrity"].get("drift_detected") is True
        ):
            observed_mismatch = (
                rebuild["state"].get("rebuild_observed_mismatch")
                if isinstance(rebuild["state"].get("rebuild_observed_mismatch"), dict)
                else {}
            )
            handoff["integrity_status"] = "blocked"
            handoff["blocked_reason"] = (
                rebuild["state"].get("rebuild_warning")
                or "rebuild integrity drift detected"
            )
            handoff["recommended_action"] = (
                "Do not treat canonical state as healthy; inspect the invalid event "
                "metadata and repair or replace the damaged transaction history "
                "before relying on capture-derived state."
            )
            if observed_mismatch:
                handoff["rebuild_observed_mismatch"] = observed_mismatch

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

        active_status = active_tx.get("status")
        active_tx_id = active_tx.get("tx_id")
        normalized_active_tx_id = self._normalize_tx_identifier(active_tx_id)
        has_active_tx = bool(normalized_active_tx_id) and (
            isinstance(active_status, str)
            and active_status.strip() not in {"done", "blocked"}
        )

        _line("ticket_id", active_tx.get("ticket_id"))
        _line("status", active_status)
        _line("current_step", active_tx.get("current_step"))
        _line("next_action", active_tx.get("next_action"))
        _line("verify_status", verify_state.get("status"))
        _line("commit_status", commit_state.get("status"))

        rebuild = self.state_rebuilder.rebuild_tx_state()
        rebuild_state = (
            rebuild.get("state") if isinstance(rebuild.get("state"), dict) else {}
        )
        rebuild_integrity = (
            rebuild_state.get("integrity")
            if isinstance(rebuild_state.get("integrity"), dict)
            else {}
        )
        observed_mismatch = (
            rebuild_state.get("rebuild_observed_mismatch")
            if isinstance(rebuild_state.get("rebuild_observed_mismatch"), dict)
            else {}
        )

        if rebuild_integrity.get("drift_detected") is True:
            lines.append("- can_start_new_ticket: no")
            lines.append("- status: blocked")
            _line("blocked_reason", rebuild_state.get("rebuild_warning"))
            invalid_reason = observed_mismatch.get("invalid_reason")
            if isinstance(invalid_reason, str) and invalid_reason.strip():
                lines.append(f"- invalid_reason: {invalid_reason.strip()}")
            lines.append(
                "- reason: canonical transaction history has integrity drift; capture and resume decisions are blocked until the invalid history is repaired"
            )
            lines.append(
                "- recommended_action: inspect rebuild_invalid_event and rebuild_observed_mismatch, then repair or replace the damaged transaction log before continuing"
            )
        elif has_active_tx:
            _line("active_ticket", active_tx.get("ticket_id") or active_tx_id)
            _line("active_status", active_status)
            _line("required_next_action", active_tx.get("next_action"))
            lines.append("- can_start_new_ticket: no")
            lines.append(
                "- reason: active transaction exists and must be resumed before starting another ticket"
            )
        else:
            lines.append("- can_start_new_ticket: yes")

        brief = "\n".join(lines).strip()
        brief = truncate_text(brief, limit=resolved_max_chars) or ""
        if len(brief) > resolved_max_chars:
            brief = brief[:resolved_max_chars].rstrip()

        return {"ok": True, "brief": brief, "max_chars": resolved_max_chars}

    def _active_tx_mismatch_error(
        self, requested_task_id: Optional[str], active_tx: Dict[str, Any]
    ) -> ValueError:
        active_tx_id = active_tx.get("tx_id")
        active_ticket_id = active_tx.get("ticket_id")
        active_status = active_tx.get("status")
        next_action = active_tx.get("next_action")

        active_value = self._normalize_tx_identifier(active_tx_id) or "unknown"
        requested_value = (
            requested_task_id.strip()
            if isinstance(requested_task_id, str) and requested_task_id.strip()
            else "unknown"
        )
        active_ticket_value = (
            active_ticket_id.strip()
            if isinstance(active_ticket_id, str) and active_ticket_id.strip()
            else "unknown"
        )
        active_status_value = (
            active_status.strip()
            if isinstance(active_status, str) and active_status.strip()
            else "unknown"
        )
        next_action_value = (
            next_action.strip()
            if isinstance(next_action, str) and next_action.strip()
            else "resume the active transaction"
        )

        return ValueError(
            "tx_id does not match active transaction: "
            f"active_tx={active_value}, requested_task={requested_value}, "
            f"active_ticket={active_ticket_value}, status={active_status_value}, "
            f"next_action={next_action_value}. "
            "Resume or complete the active transaction before starting a new ticket."
        )

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
        active_tx = self._active_tx()

        if event_type == "tx.begin":
            ticket_id = resolved_task_id or resolved_title
            tx_id = self.state_store.issue_tx_id() if ticket_id else None
        else:
            active_tx_id = active_tx.get("tx_id")
            active_ticket_id = (
                active_tx.get("ticket_id").strip()
                if isinstance(active_tx.get("ticket_id"), str)
                and active_tx.get("ticket_id").strip()
                else ""
            )
            tx_id = active_tx_id if isinstance(active_tx_id, int) else None
            ticket_id = active_ticket_id or resolved_task_id or resolved_title

        if not ticket_id:
            return None
        if event_type != "tx.begin" and tx_id is None:
            return None

        allow_recovery = event_type != "tx.begin"
        resolved_session_id = self._resolve_session_id(
            session_id,
            active_tx,
            allow_recovery=allow_recovery,
        )

        actor: Dict[str, Any] = {"tool": "ops_tools"}
        if isinstance(agent_id, str) and agent_id.strip():
            actor["agent_id"] = agent_id.strip()
        if resolved_session_id:
            actor["session_id"] = resolved_session_id

        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if isinstance(tx_state, dict):
            materialized_active_tx = tx_state.get("active_tx")
            if isinstance(materialized_active_tx, dict):
                existing_tx_id = materialized_active_tx.get("tx_id")
                if event_type == "tx.begin" or isinstance(existing_tx_id, int):
                    materialized_active_tx["tx_id"] = tx_id
                    materialized_active_tx["ticket_id"] = ticket_id
                    materialized_active_tx["phase"] = phase
                    materialized_active_tx["current_step"] = step_id
                    materialized_active_tx["session_id"] = resolved_session_id
                    return self.state_store.tx_event_append_and_state_save(
                        tx_id=tx_id,
                        ticket_id=ticket_id,
                        event_type=event_type,
                        phase=phase,
                        step_id=step_id,
                        actor=actor,
                        session_id=resolved_session_id,
                        payload=payload,
                        state=tx_state,
                    )

        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            state = rebuild["state"]
            integrity = (
                state.get("integrity")
                if isinstance(state.get("integrity"), dict)
                else {}
            )
            if integrity.get("drift_detected") is not True:
                rebuilt_active_tx = state.get("active_tx")
                if isinstance(rebuilt_active_tx, dict):
                    rebuilt_active_tx["tx_id"] = tx_id
                    rebuilt_active_tx["ticket_id"] = ticket_id
                    rebuilt_active_tx["phase"] = phase
                    rebuilt_active_tx["current_step"] = step_id
                    rebuilt_active_tx["session_id"] = resolved_session_id
                return self.state_store.tx_event_append_and_state_save(
                    tx_id=tx_id,
                    ticket_id=ticket_id,
                    event_type=event_type,
                    phase=phase,
                    step_id=step_id,
                    actor=actor,
                    session_id=resolved_session_id,
                    payload=payload,
                    state=state,
                )

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
            rebuilt_state = rebuild["state"]
            integrity = (
                rebuilt_state.get("integrity")
                if isinstance(rebuilt_state.get("integrity"), dict)
                else {}
            )
            if integrity.get("drift_detected") is not True:
                self.state_store.tx_state_save(rebuilt_state)
        return event

    def _resolve_file_intent_context(
        self,
        task_id: Optional[str],
        session_id: Optional[str],
    ) -> Tuple[Dict[str, Any], str, str]:
        resolved_task_id = self._normalize_tx_identifier(task_id)
        active_tx, active_tx_id = self._require_active_tx(task_id, allow_resume=True)
        if not resolved_task_id:
            resolved_task_id = active_tx_id
        resolved_session_id = self._resolve_session_id(session_id, active_tx)
        return active_tx, active_tx_id, resolved_session_id

    def ops_add_file_intent(
        self,
        path: str,
        operation: str,
        purpose: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_path = path.strip() if isinstance(path, str) and path.strip() else ""
        if not resolved_path:
            raise ValueError("path is required")
        resolved_operation = (
            operation.strip()
            if isinstance(operation, str) and operation.strip()
            else ""
        )
        if not resolved_operation:
            raise ValueError("operation is required")
        resolved_purpose = (
            purpose.strip() if isinstance(purpose, str) and purpose.strip() else ""
        )
        if not resolved_purpose:
            raise ValueError("purpose is required")

        active_tx, active_tx_id, resolved_session_id = (
            self._resolve_file_intent_context(task_id, session_id)
        )
        planned_step = active_tx.get("current_step")
        if not isinstance(planned_step, str) or not planned_step.strip():
            raise ValueError("current_step is required before adding file intent")

        payload = {
            "path": resolved_path,
            "operation": resolved_operation,
            "purpose": resolved_purpose,
            "planned_step": planned_step.strip(),
            "state": "planned",
            "task_id": task_id.strip()
            if isinstance(task_id, str) and task_id.strip()
            else active_tx.get("ticket_id") or "",
            "tx_id": active_tx_id,
        }

        self._emit_tx_event(
            event_type="tx.file_intent.add",
            payload=payload,
            title=active_tx.get("ticket_id") or active_tx_id,
            task_id=active_tx_id,
            phase=active_tx.get("phase")
            if isinstance(active_tx.get("phase"), str)
            else "in-progress",
            step_id=planned_step.strip(),
            session_id=resolved_session_id,
            agent_id=agent_id,
        )

        return self._workflow_success_response(
            payload=payload,
            tx_state=self._load_tx_state(),
        )

    def ops_update_file_intent(
        self,
        path: str,
        state: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_path = path.strip() if isinstance(path, str) and path.strip() else ""
        if not resolved_path:
            raise ValueError("path is required")
        resolved_state = (
            state.strip() if isinstance(state, str) and state.strip() else ""
        )
        if not resolved_state:
            raise ValueError("state is required")

        active_tx, active_tx_id, resolved_session_id = (
            self._resolve_file_intent_context(task_id, session_id)
        )
        step_id = active_tx.get("current_step")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("current_step is required before updating file intent")

        payload = {
            "path": resolved_path,
            "state": resolved_state,
            "task_id": task_id.strip()
            if isinstance(task_id, str) and task_id.strip()
            else active_tx.get("ticket_id") or "",
            "tx_id": active_tx_id,
        }

        self._emit_tx_event(
            event_type="tx.file_intent.update",
            payload=payload,
            title=active_tx.get("ticket_id") or active_tx_id,
            task_id=active_tx_id,
            phase=active_tx.get("phase")
            if isinstance(active_tx.get("phase"), str)
            else "in-progress",
            step_id=step_id.strip(),
            session_id=resolved_session_id,
            agent_id=agent_id,
        )

        return self._workflow_success_response(
            payload=payload,
            tx_state=self._load_tx_state(),
        )

    def ops_complete_file_intent(
        self,
        path: str,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_path = path.strip() if isinstance(path, str) and path.strip() else ""
        if not resolved_path:
            raise ValueError("path is required")

        active_tx, active_tx_id, resolved_session_id = (
            self._resolve_file_intent_context(task_id, session_id)
        )
        step_id = active_tx.get("current_step")
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("current_step is required before completing file intent")

        payload = {
            "path": resolved_path,
            "state": "verified",
            "task_id": task_id.strip()
            if isinstance(task_id, str) and task_id.strip()
            else active_tx.get("ticket_id") or "",
            "tx_id": active_tx_id,
        }

        self._emit_tx_event(
            event_type="tx.file_intent.complete",
            payload=payload,
            title=active_tx.get("ticket_id") or active_tx_id,
            task_id=active_tx_id,
            phase=active_tx.get("phase")
            if isinstance(active_tx.get("phase"), str)
            else "in-progress",
            step_id=step_id.strip(),
            session_id=resolved_session_id,
            agent_id=agent_id,
        )

        return self._workflow_success_response(
            payload=payload,
            tx_state=self._load_tx_state(),
        )

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

        resolved_task_id = self._normalize_tx_identifier(task_id)
        requested_status = (
            status.strip() if isinstance(status, str) and status.strip() else ""
        )
        tx_phase = "in-progress"
        tx_step_id = resolved_task_id or "task"

        active_tx = self._active_tx()
        identity = self._active_tx_identity(active_tx)
        terminal_active_tx = self._is_terminal_active_tx(active_tx)
        has_active_tx = bool(identity["tx_id"]) and not terminal_active_tx

        if not has_active_tx:
            if not resolved_task_id:
                raise ValueError("task_id is required to bootstrap tx.begin")
            begin_conflict = self._canonical_begin_conflict(resolved_task_id)
            if begin_conflict is not None:
                raise begin_conflict
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
            active_tx, resolved_tx_id = self._require_active_tx(
                resolved_task_id, allow_resume=True
            )
        else:
            active_tx, resolved_tx_id = self._require_active_tx(
                resolved_task_id or None, allow_resume=True
            )
            if not resolved_task_id:
                resolved_task_id = (
                    active_tx.get("ticket_id").strip()
                    if isinstance(active_tx.get("ticket_id"), str)
                    and active_tx.get("ticket_id").strip()
                    else resolved_tx_id
                )
                payload["task_id"] = resolved_task_id
            tx_step_id = resolved_task_id or tx_step_id

        if requested_status and requested_status != "in-progress":
            payload["requested_status"] = requested_status

        event = self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": "task started"},
            title=resolved_task_id or title.strip(),
            task_id=resolved_task_id,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        return self._workflow_success_response(
            payload=payload,
            event=event,
            tx_state=self._load_tx_state(),
        )

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

        resolved_task_id = self._normalize_tx_identifier(task_id)
        active_tx, active_tx_id = self._require_active_tx(task_id, allow_resume=True)
        active_ticket_id = (
            active_tx.get("ticket_id").strip()
            if isinstance(active_tx.get("ticket_id"), str)
            and active_tx.get("ticket_id").strip()
            else ""
        )
        if not resolved_task_id:
            resolved_task_id = active_ticket_id or active_tx_id
        if resolved_task_id and "task_id" not in payload:
            payload["task_id"] = resolved_task_id

        resolved_status = (
            status.strip() if isinstance(status, str) and status.strip() else ""
        )
        if resolved_status == "done":
            raise ValueError("use ops_end_task for terminal done state")
        if resolved_status == "blocked":
            raise ValueError("use ops_end_task for terminal blocked state")

        allowed_statuses = {"", "in-progress", "checking", "verified", "committed"}
        if resolved_status not in allowed_statuses:
            raise ValueError("unsupported status for ops_update_task")

        tx_phase = resolved_status or (
            active_tx.get("phase").strip()
            if isinstance(active_tx.get("phase"), str)
            and active_tx.get("phase").strip()
            else "in-progress"
        )
        tx_step_id = resolved_task_id or active_ticket_id or active_tx_id or "task"
        description = payload.get("note") or "task updated"
        event = self._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": tx_step_id, "description": description},
            title=resolved_task_id or active_ticket_id or "task",
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
                title=resolved_task_id or active_ticket_id or "task",
                task_id=resolved_task_id or None,
                phase=tx_phase,
                step_id=tx_step_id,
                session_id=session_id,
                agent_id=agent_id,
            )

        return self._workflow_success_response(
            payload=payload,
            event=event,
            tx_state=self._load_tx_state(),
        )

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

        resolved_task_id = self._normalize_tx_identifier(task_id)
        active_tx, active_tx_id = self._require_active_tx(task_id, allow_resume=True)
        active_ticket_id = (
            active_tx.get("ticket_id").strip()
            if isinstance(active_tx.get("ticket_id"), str)
            and active_tx.get("ticket_id").strip()
            else ""
        )
        if not resolved_task_id:
            resolved_task_id = active_ticket_id or active_tx_id
        if resolved_task_id and "task_id" not in payload:
            payload["task_id"] = resolved_task_id

        tx_phase = (
            status.strip() if isinstance(status, str) and status.strip() else "done"
        )
        if tx_phase not in {"done", "blocked"}:
            raise ValueError("ops_end_task status must be done or blocked")
        if tx_phase == "done":
            commit_state = (
                active_tx.get("commit_state")
                if isinstance(active_tx.get("commit_state"), dict)
                else {}
            )
            active_phase = active_tx.get("phase")
            active_status = active_tx.get("status")
            commit_passed = commit_state.get("status") == "passed"
            committed_phase = (
                isinstance(active_phase, str) and active_phase.strip() == "committed"
            )
            committed_status = (
                isinstance(active_status, str) and active_status.strip() == "committed"
            )
            if not (commit_passed or committed_phase or committed_status):
                raise ValueError(
                    "cannot mark task done before commit is finished; "
                    "complete commit workflow first"
                )

        tx_step_id = resolved_task_id or active_ticket_id or active_tx_id or "task"
        end_type = "tx.end.blocked" if tx_phase == "blocked" else "tx.end.done"
        end_payload = {"summary": payload.get("summary", "")}
        if isinstance(payload.get("next_action"), str) and payload.get("next_action"):
            end_payload["next_action"] = payload.get("next_action")
        if end_type == "tx.end.blocked":
            end_payload["reason"] = payload.get("summary", "")
        event = self._emit_tx_event(
            event_type=end_type,
            payload=end_payload,
            title=resolved_task_id or active_ticket_id or "task",
            task_id=resolved_task_id or None,
            phase=tx_phase,
            step_id=tx_step_id,
            session_id=session_id,
            agent_id=agent_id,
        )

        response_state = self._load_tx_state()
        active_response_tx = (
            response_state.get("active_tx")
            if isinstance(response_state.get("active_tx"), dict)
            else {}
        )
        verify_state = (
            active_response_tx.get("verify_state")
            if isinstance(active_response_tx.get("verify_state"), dict)
            else {}
        )
        commit_state = (
            active_response_tx.get("commit_state")
            if isinstance(active_response_tx.get("commit_state"), dict)
            else {}
        )
        source_verify_state = (
            active_tx.get("verify_state")
            if isinstance(active_tx.get("verify_state"), dict)
            else {}
        )
        source_commit_state = (
            active_tx.get("commit_state")
            if isinstance(active_tx.get("commit_state"), dict)
            else {}
        )
        if source_verify_state and (
            not verify_state
            or verify_state.get("status") != source_verify_state.get("status")
            or verify_state.get("last_result") != source_verify_state.get("last_result")
        ):
            active_response_tx["verify_state"] = json.loads(
                json.dumps(source_verify_state, ensure_ascii=False)
            )
        if source_commit_state and (
            not commit_state
            or commit_state.get("status") != source_commit_state.get("status")
            or commit_state.get("last_result") != source_commit_state.get("last_result")
        ):
            active_response_tx["commit_state"] = json.loads(
                json.dumps(source_commit_state, ensure_ascii=False)
            )

        guidance_overrides: Dict[str, Any] = {}
        if tx_phase == "done":
            guidance_overrides["next_action"] = "tx.begin"
            guidance_overrides["followup_tool"] = None
        return self._workflow_success_response(
            payload=payload,
            event=event,
            tx_state=response_state,
            **guidance_overrides,
        )

    def ops_capture_state(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if not rebuild.get("ok"):
            return rebuild

        state = rebuild.get("state") or {}
        integrity = (
            state.get("integrity") if isinstance(state.get("integrity"), dict) else {}
        )
        if integrity.get("drift_detected") is True:
            active_tx = (
                state.get("active_tx")
                if isinstance(state.get("active_tx"), dict)
                else {}
            )
            response = build_failure_response(
                error_code="integrity_drift_detected",
                reason="rebuild integrity drift detected",
                tx_state=state,
                recoverable=False,
                recommended_next_tool="tx_state_rebuild",
                recommended_action=(
                    "Do not capture or trust canonical state until the invalid transaction "
                    "history is repaired. Inspect rebuild_invalid_event and "
                    "rebuild_observed_mismatch to identify the offending lifecycle event."
                ),
                blocked=True,
                rebuild_warning=state.get("rebuild_warning"),
                rebuild_invalid_seq=state.get("rebuild_invalid_seq"),
                rebuild_observed_mismatch=state.get("rebuild_observed_mismatch"),
            )
            response["last_applied_seq"] = state.get("last_applied_seq")
            response["integrity"] = integrity
            response["active_tx"] = active_tx
            return response

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

        response = self._workflow_success_response(tx_state=state)
        response["state"] = save_result
        response["last_applied_seq"] = last_seq_value
        response["integrity"] = integrity
        response["integrity_status"] = (
            "blocked" if integrity.get("drift_detected") is True else "ok"
        )
        response["can_start_new_ticket"] = response.get("can_start_new_ticket")
        response["resume_required"] = response.get("resume_required")
        return response

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
