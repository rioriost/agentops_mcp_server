from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .git_repo import GitRepo
from .state_rebuilder import StateRebuilder
from .state_store import StateStore
from .verify_runner import VerifyRunner
from .workflow_response import build_structured_helper_failure, build_success_response


class CommitManager:
    def __init__(
        self,
        git_repo: GitRepo,
        verify_runner: VerifyRunner,
        state_store: StateStore,
        state_rebuilder: StateRebuilder,
    ) -> None:
        self.git_repo = git_repo
        self.verify_runner = verify_runner
        self.state_store = state_store
        self.state_rebuilder = state_rebuilder
        self.repo_context = state_store.repo_context
        self._verify_started_in_call = False

    def _is_valid_materialized_tx_state(self, tx_state: Any) -> bool:
        if not isinstance(tx_state, dict):
            return False

        active_tx = tx_state.get("active_tx")
        status = tx_state.get("status")
        next_action = tx_state.get("next_action")
        verify_state = tx_state.get("verify_state")
        commit_state = tx_state.get("commit_state")
        semantic_summary = tx_state.get("semantic_summary")

        if active_tx is None:
            return (
                status is None
                and isinstance(next_action, str)
                and bool(next_action.strip())
                and verify_state is None
                and commit_state is None
                and semantic_summary is None
            )

        if not isinstance(active_tx, dict):
            return False
        if not isinstance(status, str) or not status.strip():
            return False
        if not isinstance(next_action, str) or not next_action.strip():
            return False
        if not isinstance(verify_state, dict):
            return False
        if not isinstance(commit_state, dict):
            return False
        if not isinstance(semantic_summary, str) or not semantic_summary.strip():
            return False

        tx_id = active_tx.get("tx_id")
        ticket_id = active_tx.get("ticket_id")
        if isinstance(tx_id, bool) or not isinstance(tx_id, int):
            return False
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return False

        session_id = active_tx.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            return False

        return True

    def _load_resume_state(self) -> Dict[str, Any]:
        baseline = {
            "active_tx": None,
            "status": None,
            "next_action": "tx.begin",
            "verify_state": None,
            "commit_state": None,
            "semantic_summary": None,
            "integrity": {},
        }

        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if self._is_valid_materialized_tx_state(tx_state):
            return tx_state

        materialized_state = tx_state if isinstance(tx_state, dict) else {}
        materialized_active_tx = (
            materialized_state.get("active_tx")
            if isinstance(materialized_state.get("active_tx"), dict)
            else None
        )
        materialized_status = materialized_state.get("status")
        materialized_next_action = materialized_state.get("next_action")
        materialized_requests_rebuild = (
            tx_state is None
            or materialized_active_tx is None
            or not isinstance(materialized_status, str)
            or not materialized_status.strip()
            or not isinstance(materialized_next_action, str)
            or not materialized_next_action.strip()
        )

        if materialized_requests_rebuild:
            rebuild = self.state_rebuilder.rebuild_tx_state()
            if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
                rebuilt_state = rebuild["state"]
                integrity = (
                    rebuilt_state.get("integrity")
                    if isinstance(rebuilt_state.get("integrity"), dict)
                    else {}
                )
                if integrity.get("drift_detected") is True:
                    raise RuntimeError(
                        build_structured_helper_failure(
                            error_code="integrity_blocked",
                            reason="resume blocked by ambiguous canonical persistence",
                            tx_state=rebuilt_state,
                            recommended_next_tool="tx_state_rebuild",
                            recommended_action="Repair the invalid canonical history before resuming the exact active transaction.",
                            recoverable=False,
                            blocked=True,
                            rebuild_warning=rebuilt_state.get("rebuild_warning"),
                            rebuild_invalid_seq=rebuilt_state.get(
                                "rebuild_invalid_seq"
                            ),
                            rebuild_observed_mismatch=rebuilt_state.get(
                                "rebuild_observed_mismatch"
                            ),
                        )
                    )
                if self._is_valid_materialized_tx_state(rebuilt_state):
                    return rebuilt_state
                raise RuntimeError(
                    build_structured_helper_failure(
                        error_code="invalid_ordering",
                        reason="resume blocked because rebuilt canonical state is incomplete",
                        tx_state=rebuilt_state,
                        recommended_next_tool="tx_state_rebuild",
                        recommended_action="Repair canonical persistence so rebuild yields a complete exact active transaction state with top-level next_action.",
                    )
                )

            if tx_state is None:
                return baseline

            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="resume blocked by malformed canonical persistence",
                    tx_state=materialized_state or None,
                    recommended_next_tool="tx_state_rebuild",
                    recommended_action="Repair malformed canonical persistence before resuming the exact active transaction.",
                )
            )

        raise RuntimeError(
            build_structured_helper_failure(
                error_code="invalid_ordering",
                reason="resume blocked because materialized canonical state is malformed",
                tx_state=materialized_state or None,
                recommended_next_tool="ops_capture_state",
                recommended_action="Restore canonical top-level status and next_action before resuming the exact active transaction.",
            )
        )

    def _load_tx_context(self) -> Optional[Dict[str, Any]]:
        tx_state = self._load_resume_state()
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            return None
        status = tx_state.get("status")
        if not isinstance(status, str) or not status.strip():
            return None
        if status.strip() in {"done", "blocked"}:
            return None
        tx_id = active_tx.get("tx_id")
        ticket_id = active_tx.get("ticket_id")
        next_action = tx_state.get("next_action")
        if isinstance(tx_id, bool) or not isinstance(tx_id, int):
            return None
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return None
        if not isinstance(next_action, str) or not next_action.strip():
            return None
        session_id = active_tx.get("session_id")
        resolved_session_id = (
            session_id.strip()
            if isinstance(session_id, str) and session_id.strip()
            else "resume"
        )
        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id.strip(),
            "next_action": next_action.strip(),
            "session_id": resolved_session_id,
        }

    def _event_log_empty(self) -> bool:
        last = self.state_store.read_last_json_line(self.repo_context.tx_event_log)
        return last is None

    def _active_tx_from_state(self, tx_state: Any) -> Optional[Dict[str, Any]]:
        if not self._is_valid_materialized_tx_state(tx_state):
            return None
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            return None
        tx_id = active_tx.get("tx_id")
        ticket_id = active_tx.get("ticket_id")
        next_action = tx_state.get("next_action")
        session_id = active_tx.get("session_id")
        if isinstance(tx_id, bool) or not isinstance(tx_id, int):
            return None
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return None
        if not isinstance(next_action, str) or not next_action.strip():
            return None
        resolved_session_id = (
            session_id.strip()
            if isinstance(session_id, str) and session_id.strip()
            else "resume"
        )
        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id.strip(),
            "next_action": next_action.strip(),
            "session_id": resolved_session_id,
        }

    def _matching_active_context_from_rebuild(
        self, requested_context: Dict[str, str]
    ) -> Tuple[
        Optional[Dict[str, str]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]
    ]:
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if not rebuild.get("ok") or not isinstance(rebuild.get("state"), dict):
            return None, None, None

        rebuilt_state = rebuild["state"]
        integrity = (
            rebuilt_state.get("integrity")
            if isinstance(rebuilt_state.get("integrity"), dict)
            else {}
        )
        if integrity.get("drift_detected") is True:
            return None, rebuilt_state, integrity

        rebuilt_context = self._active_tx_from_state(rebuilt_state)
        if not rebuilt_context:
            return None, rebuilt_state, integrity

        requested_tx_id = requested_context["tx_id"]
        if rebuilt_context["tx_id"] != requested_tx_id:
            return None, rebuilt_state, integrity

        terminal = (
            rebuilt_state.get("status") in {"done", "blocked"}
            if isinstance(rebuilt_state, dict)
            else False
        )
        if terminal:
            return None, rebuilt_state, integrity

        return rebuilt_context, rebuilt_state, integrity

    def _emit_tx_begin_with_context(self, context: Dict[str, str]) -> None:
        tx_state = self._load_resume_state()
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            active_tx = {}
            tx_state["active_tx"] = active_tx
            tx_state["status"] = "in-progress"
            tx_state["next_action"] = "tx.verify.start"
            tx_state["verify_state"] = {"status": "not_started", "last_result": None}
            tx_state["commit_state"] = {"status": "not_started", "last_result": None}
            tx_state["semantic_summary"] = "Transaction started"

        active_tx["tx_id"] = context["tx_id"]
        active_tx["ticket_id"] = context["ticket_id"]
        active_tx["status"] = "in-progress"
        active_tx["phase"] = "in-progress"
        active_tx["current_step"] = "none"
        active_tx["last_completed_step"] = ""
        active_tx["next_action"] = "tx.verify.start"
        active_tx["semantic_summary"] = "Transaction started"
        active_tx["user_intent"] = active_tx.get("user_intent")
        active_tx["session_id"] = context["session_id"]
        active_tx["verify_state"] = active_tx.get("verify_state") or {
            "status": "not_started",
            "last_result": None,
        }
        active_tx["commit_state"] = active_tx.get("commit_state") or {
            "status": "not_started",
            "last_result": None,
        }
        active_tx["file_intents"] = active_tx.get("file_intents") or []

        self.state_store.tx_event_append_and_state_save(
            tx_id=context["tx_id"],
            ticket_id=context["ticket_id"],
            event_type="tx.begin",
            phase="in-progress",
            step_id="none",
            actor={"tool": "commit_manager"},
            session_id=context["session_id"],
            payload={
                "ticket_id": context["ticket_id"],
                "ticket_title": context["ticket_id"],
            },
            state=tx_state,
        )

    def _ensure_tx_begin(self) -> None:
        context = self._load_tx_context()
        if not context:
            return

        if not self._event_log_empty():
            return

        rebuild_context, rebuilt_state, integrity = (
            self._matching_active_context_from_rebuild(context)
        )
        if rebuild_context:
            tx_state = self._load_resume_state()
            if self._is_valid_materialized_tx_state(rebuilt_state):
                tx_state = rebuilt_state
            if isinstance(tx_state, dict):
                active_tx = tx_state.get("active_tx")
                if not isinstance(active_tx, dict):
                    active_tx = {}
                    tx_state["active_tx"] = active_tx
                active_tx["tx_id"] = rebuild_context["tx_id"]
                active_tx["ticket_id"] = rebuild_context["ticket_id"]
                active_tx["phase"] = "in-progress"
                active_tx["current_step"] = "none"
                active_tx["session_id"] = rebuild_context["session_id"]
                self.state_store.tx_state_save(tx_state)
            return

        if isinstance(integrity, dict) and integrity.get("drift_detected") is True:
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="integrity_blocked",
                    reason="helper bootstrap blocked by canonical integrity drift",
                    tx_state=rebuilt_state,
                    recommended_next_tool="tx_state_rebuild",
                    recommended_action="Repair the invalid canonical history before allowing helper bootstrap to emit tx.begin.",
                    recoverable=False,
                    blocked=True,
                    rebuild_warning=(
                        rebuilt_state.get("rebuild_warning")
                        if isinstance(rebuilt_state, dict)
                        else None
                    ),
                    rebuild_invalid_seq=(
                        rebuilt_state.get("rebuild_invalid_seq")
                        if isinstance(rebuilt_state, dict)
                        else None
                    ),
                    rebuild_observed_mismatch=(
                        rebuilt_state.get("rebuild_observed_mismatch")
                        if isinstance(rebuilt_state, dict)
                        else None
                    ),
                )
            )

        self._emit_tx_begin_with_context(context)

    def _ensure_verify_started(self) -> None:
        tx_state = self._load_resume_state()
        if not self._is_valid_materialized_tx_state(tx_state):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; tx_state missing",
                    tx_state=None,
                    recommended_next_tool="repo_verify",
                    recommended_action="Ensure canonical transaction state is materialized before returning verify results.",
                )
            )
        canonical_status = tx_state.get("status")
        canonical_next_action = tx_state.get("next_action")
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; active_tx missing",
                    tx_state=tx_state,
                    recommended_next_tool="repo_verify",
                    recommended_action="Restore the exact active transaction state before returning verify results.",
                )
            )
        if (
            not isinstance(canonical_status, str)
            or not canonical_status.strip()
            or canonical_status.strip() in {"done", "blocked"}
        ):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; active transaction is not resumable",
                    tx_state=tx_state,
                    recommended_next_tool="ops_update_task",
                    recommended_action="Resume the exact active non-terminal transaction before returning verify results.",
                )
            )
        if (
            not isinstance(canonical_next_action, str)
            or not canonical_next_action.strip()
        ):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; canonical next_action missing",
                    tx_state=tx_state,
                    recommended_next_tool="ops_update_task",
                    recommended_action="Restore the exact active transaction with a valid top-level next_action before returning verify results.",
                )
            )
        verify_state = (
            tx_state.get("verify_state")
            if isinstance(tx_state.get("verify_state"), dict)
            else {}
        )
        if verify_state.get("status") == "running":
            return
        if self._verify_started_in_call:
            rebuild = self.state_rebuilder.rebuild_tx_state()
            if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
                rebuilt_state = rebuild["state"]
                integrity = (
                    rebuilt_state.get("integrity")
                    if isinstance(rebuilt_state.get("integrity"), dict)
                    else {}
                )
                if integrity.get("drift_detected") is not True:
                    refreshed_active_tx = rebuilt_state.get("active_tx")
                    if isinstance(refreshed_active_tx, dict):
                        refreshed_verify_state = (
                            rebuilt_state.get("verify_state")
                            if isinstance(rebuilt_state.get("verify_state"), dict)
                            else {}
                        )
                        if refreshed_verify_state.get("status") == "running":
                            self.state_store.tx_state_save(rebuilt_state)
                            return
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start emitted but tx_state was not updated to running",
                    tx_state=tx_state,
                    recommended_next_tool="repo_verify",
                    recommended_action="Repair state persistence so verify.start updates canonical verify_state before continuing.",
                )
            )
        raise RuntimeError(
            build_structured_helper_failure(
                error_code="begin_required",
                reason="verify.start not recorded; tx.begin required before verify results",
                tx_state=tx_state,
                recommended_next_tool="ops_start_task",
                recommended_action="Start or resume the canonical transaction before returning verify results.",
            )
        )

    def _emit_tx_event(
        self,
        *,
        event_type: str,
        payload: Dict[str, Any],
        phase_override: Optional[str] = None,
        step_id_override: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        context = self._load_tx_context()
        if not context:
            return None
        phase = phase_override or context["next_action"]
        step_id = step_id_override or "commit"
        actor = {"tool": "commit_manager"}
        tx_state = self._load_resume_state()
        if self._is_valid_materialized_tx_state(tx_state):
            active_tx = tx_state.get("active_tx")
            if isinstance(active_tx, dict):
                active_tx["tx_id"] = context["tx_id"]
                active_tx["ticket_id"] = context["ticket_id"]
                active_tx["phase"] = phase
                active_tx["current_step"] = step_id
                if isinstance(context.get("session_id"), str):
                    active_tx["session_id"] = context["session_id"]
                if event_type == "tx.verify.start":
                    active_tx["status"] = "checking"
                    active_tx["verify_state"] = {
                        "status": "running",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Verification started"
                    active_tx["next_action"] = "tx.verify.pass"
                elif event_type == "tx.verify.pass":
                    active_tx["status"] = "verified"
                    active_tx["verify_state"] = {
                        "status": "passed",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Verification passed"
                    active_tx["next_action"] = "tx.commit.start"
                elif event_type == "tx.verify.fail":
                    active_tx["status"] = "checking"
                    active_tx["verify_state"] = {
                        "status": "failed",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Verification failed"
                    active_tx["next_action"] = "fix and re-verify"
                elif event_type == "tx.commit.start":
                    active_tx["status"] = "verified"
                    active_tx["commit_state"] = {
                        "status": "running",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Commit started"
                    active_tx["next_action"] = "tx.commit.done"
                elif event_type == "tx.commit.done":
                    active_tx["status"] = "committed"
                    active_tx["commit_state"] = {
                        "status": "passed",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Commit completed"
                    active_tx["next_action"] = "tx.end.done"
                elif event_type == "tx.commit.fail":
                    active_tx["status"] = "verified"
                    active_tx["commit_state"] = {
                        "status": "failed",
                        "last_result": payload,
                    }
                    active_tx["semantic_summary"] = "Commit failed"
                    active_tx["next_action"] = "tx.commit.start"
            return self.state_store.tx_event_append_and_state_save(
                tx_id=context["tx_id"],
                ticket_id=context["ticket_id"],
                event_type=event_type,
                phase=phase,
                step_id=step_id,
                actor=actor,
                session_id=context["session_id"],
                payload=payload,
                state=tx_state,
            )

        return self.state_store.tx_event_append(
            tx_id=context["tx_id"],
            ticket_id=context["ticket_id"],
            event_type=event_type,
            phase=phase,
            step_id=step_id,
            actor=actor,
            session_id=context["session_id"],
            payload=payload,
        )

    def _commit_message_from_status(self, status_lines: List[str]) -> str:
        count = len(status_lines)
        if count == 0:
            return "chore: no-op"
        return f"chore: update {count} file(s)"

    def _normalize_commit_message(self, message: str) -> str:
        msg = message.strip().replace("\n", " ")
        if len(msg) > 80:
            msg = msg[:77].rstrip() + "..."
        return msg

    def _branch_name(self) -> str:
        try:
            branch = self.git_repo.git("rev-parse", "--abbrev-ref", "HEAD")
        except Exception:  # noqa: BLE001
            branch = "unknown"
        branch = branch.strip() if isinstance(branch, str) else ""
        return branch or "unknown"

    def _diff_summary(self, cached: bool = False) -> str:
        try:
            summary = (
                self.git_repo.diff_stat_cached()
                if cached
                else self.git_repo.diff_stat()
            )
        except Exception:  # noqa: BLE001
            summary = ""
        summary = summary.strip() if isinstance(summary, str) else ""
        return summary or "no changes"

    def _run_git_commit(self, message: str) -> Tuple[str, str]:
        summary = self._diff_summary(cached=True)
        branch = self._branch_name()
        try:
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.repo_context.get_repo_root()),
                check=True,
            )
            sha = self.git_repo.git("rev-parse", "HEAD")
        except Exception as exc:  # noqa: BLE001
            self._emit_tx_event(
                event_type="tx.commit.fail",
                payload={"error": str(exc), "summary": "commit failed"},
                phase_override="verified",
            )
            raise
        self._emit_tx_event(
            event_type="tx.commit.done",
            payload={
                "sha": sha,
                "summary": summary,
                "branch": branch,
                "diff_summary": summary,
            },
            phase_override="committed",
        )
        return sha, summary

    def _workflow_guidance(self) -> Dict[str, Any]:
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if not isinstance(tx_state, dict):
            tx_state = {
                "active_tx": None,
                "status": None,
                "next_action": "tx.begin",
                "verify_state": None,
                "commit_state": None,
                "semantic_summary": None,
                "integrity": {},
            }

        response = build_success_response(tx_state=tx_state)
        active_tx = response.get("active_tx")
        if not isinstance(active_tx, dict):
            active_tx = {}

        return {
            "tx_status": response["canonical_status"],
            "tx_phase": response["canonical_phase"],
            "next_action": response["next_action"],
            "terminal": response["terminal"],
            "requires_followup": response["requires_followup"],
            "followup_tool": response["followup_tool"],
            "canonical_status": response["canonical_status"],
            "canonical_phase": response["canonical_phase"],
            "active_tx_id": response["active_tx_id"],
            "active_ticket_id": response["active_ticket_id"],
            "current_step": response["current_step"],
            "verify_status": response["verify_status"],
            "commit_status": response["commit_status"],
            "integrity_status": response["integrity_status"],
            "can_start_new_ticket": response["can_start_new_ticket"],
            "resume_required": response["resume_required"],
            "active_tx": active_tx,
        }

    def commit_if_verified(
        self, message: str, timeout_sec: Optional[int] = None
    ) -> Dict[str, Any]:
        self._verify_started_in_call = False
        self._ensure_tx_begin()
        self._emit_tx_event(
            event_type="tx.verify.start",
            payload={"command": str(self.repo_context.verify)},
            phase_override="checking",
        )
        self._verify_started_in_call = True
        self._ensure_verify_started()
        verify_result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
        if not verify_result["ok"]:
            self._emit_tx_event(
                event_type="tx.verify.fail",
                payload={
                    "ok": False,
                    "returncode": verify_result.get("returncode"),
                    "error": verify_result.get("stderr") or "verify failed",
                },
                phase_override="checking",
            )
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="verify_failed",
                    reason=f"verify failed (code={verify_result['returncode']}): {verify_result['stderr']}",
                    tx_state=self.state_store.read_json_file(
                        self.repo_context.tx_state
                    ),
                    recommended_next_tool="repo_verify",
                    recommended_action="Repair the verification failure and rerun verification before attempting commit.",
                )
            )
        self._emit_tx_event(
            event_type="tx.verify.pass",
            payload={
                "ok": True,
                "returncode": verify_result.get("returncode"),
                "summary": verify_result.get("stdout") or "verify passed",
            },
            phase_override="verified",
        )
        commit_start_message = (
            self._normalize_commit_message(message) or "chore: update"
        )
        branch = self._branch_name()
        diff_summary = self._diff_summary()
        self._emit_tx_event(
            event_type="tx.commit.start",
            payload={
                "message": commit_start_message,
                "files": "auto",
                "branch": branch,
                "diff_summary": diff_summary,
            },
            phase_override="verified",
        )
        self.git_repo.git("add", "-A")

        msg = commit_start_message
        sha, _summary = self._run_git_commit(msg)
        result: Dict[str, Any] = {"ok": True, "sha": sha, "message": msg}
        result.update(self._workflow_guidance())
        return result

    def repo_commit(
        self,
        message: Optional[str] = None,
        files: Optional[str] = "auto",
        run_verify: Optional[bool] = None,
        timeout_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._verify_started_in_call = False
        if run_verify:
            self._emit_tx_event(
                event_type="tx.verify.start",
                payload={"command": str(self.repo_context.verify)},
                phase_override="checking",
            )
            self._verify_started_in_call = True
            self._ensure_verify_started()
            verify_result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
            if not verify_result["ok"]:
                stderr = (verify_result.get("stderr") or "").strip()
                stdout = (verify_result.get("stdout") or "").strip()
                details = stderr or stdout or "unknown error"
                self._emit_tx_event(
                    event_type="tx.verify.fail",
                    payload={
                        "ok": False,
                        "returncode": verify_result.get("returncode"),
                        "error": details,
                    },
                    phase_override="checking",
                )
                raise RuntimeError(
                    build_structured_helper_failure(
                        error_code="verify_failed",
                        reason=f"verify failed (code={verify_result['returncode']}): {details}",
                        tx_state=self.state_store.read_json_file(
                            self.repo_context.tx_state
                        ),
                        recommended_next_tool="repo_verify",
                        recommended_action="Repair the verification failure and rerun verification before attempting commit.",
                    )
                )
            self._emit_tx_event(
                event_type="tx.verify.pass",
                payload={
                    "ok": True,
                    "returncode": verify_result.get("returncode"),
                    "summary": verify_result.get("stdout") or "verify passed",
                },
                phase_override="verified",
            )

        status_lines = self.git_repo.status_porcelain()
        commit_start_message = (message or "").strip().replace("\n", " ")
        if not commit_start_message:
            commit_start_message = self._commit_message_from_status(status_lines)
        commit_start_message = self._normalize_commit_message(commit_start_message)
        branch = self._branch_name()
        diff_summary = self._diff_summary()
        self._emit_tx_event(
            event_type="tx.commit.start",
            payload={
                "message": commit_start_message,
                "files": files,
                "branch": branch,
                "diff_summary": diff_summary,
            },
            phase_override="verified",
        )
        if not status_lines:
            self._emit_tx_event(
                event_type="tx.commit.fail",
                payload={
                    "error": "no changes to commit",
                    "summary": "no changes to commit",
                },
                phase_override="verified",
            )
            result = build_structured_helper_failure(
                error_code="invalid_ordering",
                reason="no changes to commit",
                tx_state=self.state_store.read_json_file(self.repo_context.tx_state),
                recommended_next_tool="ops_end_task",
                recommended_action="If work is already verified and nothing remains to commit, close the transaction explicitly or make additional changes before retrying commit.",
            )
            result.update(self._workflow_guidance())
            return result

        resolved_files: Any = files if files is not None else "auto"
        if isinstance(resolved_files, str):
            normalized = resolved_files.strip()
            if not normalized or normalized == "auto":
                resolved_files = "auto"
            else:
                resolved_files = [p.strip() for p in normalized.split(",") if p.strip()]

        if resolved_files == "auto":
            self.git_repo.git("add", "-A")
        else:
            if isinstance(resolved_files, list):
                paths = resolved_files
            else:
                paths = [str(resolved_files)]
            if not paths:
                self._emit_tx_event(
                    event_type="tx.commit.fail",
                    payload={
                        "error": "no files specified",
                        "summary": "no files specified",
                    },
                    phase_override="verified",
                )
                result = build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="no files specified",
                    tx_state=self.state_store.read_json_file(
                        self.repo_context.tx_state
                    ),
                    recommended_next_tool="repo_commit",
                    recommended_action="Specify commit paths or use auto staging before retrying commit.",
                )
                result.update(self._workflow_guidance())
                return result
            self.git_repo.git("add", *paths)

        msg = commit_start_message

        sha, summary = self._run_git_commit(msg)
        result: Dict[str, Any] = {
            "ok": True,
            "sha": sha,
            "message": msg,
            "summary": summary,
        }
        result.update(self._workflow_guidance())
        return result
