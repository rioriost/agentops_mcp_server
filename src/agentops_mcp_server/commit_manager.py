from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .git_repo import GitRepo
from .state_rebuilder import StateRebuilder
from .state_store import StateStore
from .verify_runner import VerifyRunner
from .workflow_response import (
    build_guidance_from_active_tx,
    build_structured_helper_failure,
)


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

    def _load_tx_context(self) -> Optional[Dict[str, str]]:
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if not isinstance(tx_state, dict):
            return None
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            return None
        tx_id = active_tx.get("tx_id")
        ticket_id = active_tx.get("ticket_id")
        if not isinstance(tx_id, str) or not tx_id.strip():
            return None
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return None
        phase = active_tx.get("phase")
        if not isinstance(phase, str) or not phase.strip():
            phase = active_tx.get("status")
        if not isinstance(phase, str) or not phase.strip():
            phase = "in-progress"
        step_id = active_tx.get("current_step")
        if not isinstance(step_id, str) or not step_id.strip():
            step_id = "commit"
        session_id = active_tx.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "phase": phase,
            "step_id": step_id,
            "session_id": session_id.strip(),
        }

    def _event_log_empty(self) -> bool:
        last = self.state_store.read_last_json_line(self.repo_context.tx_event_log)
        return last is None

    def _ensure_tx_begin(self) -> None:
        context = self._load_tx_context()
        if not context:
            return
        if not self._event_log_empty():
            return
        self._emit_tx_event(
            event_type="tx.begin",
            payload={
                "ticket_id": context["ticket_id"],
                "ticket_title": context["ticket_id"],
            },
            phase_override=context["phase"],
            step_id_override="none",
        )

    def _ensure_verify_started(self) -> None:
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if not isinstance(tx_state, dict):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; tx_state missing",
                    tx_state=None,
                    recommended_next_tool="repo_verify",
                    recommended_action="Ensure canonical transaction state is materialized before returning verify results.",
                )["reason"]
            )
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            raise RuntimeError(
                build_structured_helper_failure(
                    error_code="invalid_ordering",
                    reason="verify.start not recorded; active_tx missing",
                    tx_state=tx_state,
                    recommended_next_tool="repo_verify",
                    recommended_action="Restore the active transaction state before returning verify results.",
                )["reason"]
            )
        verify_state = (
            active_tx.get("verify_state")
            if isinstance(active_tx.get("verify_state"), dict)
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
                            refreshed_active_tx.get("verify_state")
                            if isinstance(refreshed_active_tx.get("verify_state"), dict)
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
                )["reason"]
            )
        raise RuntimeError(
            build_structured_helper_failure(
                error_code="begin_required",
                reason="verify.start not recorded; tx.begin required before verify results",
                tx_state=tx_state,
                recommended_next_tool="ops_start_task",
                recommended_action="Start or resume the canonical transaction before returning verify results.",
            )["reason"]
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
        phase = phase_override or context["phase"]
        step_id = step_id_override or context["step_id"]
        actor = {"tool": "commit_manager"}
        tx_state = self.state_store.read_json_file(self.repo_context.tx_state)
        if isinstance(tx_state, dict):
            active_tx = tx_state.get("active_tx")
            if isinstance(active_tx, dict):
                active_tx["tx_id"] = context["tx_id"]
                active_tx["ticket_id"] = context["ticket_id"]
                active_tx["status"] = phase
                active_tx["phase"] = phase
                active_tx["current_step"] = step_id
                if isinstance(context.get("session_id"), str):
                    active_tx["session_id"] = context["session_id"]
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

        rebuild_fn = getattr(self.state_rebuilder, "rebuild_tx_state", None)
        if callable(rebuild_fn):
            rebuild = rebuild_fn()
            if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
                state = rebuild["state"]
                integrity = (
                    state.get("integrity")
                    if isinstance(state.get("integrity"), dict)
                    else {}
                )
                if integrity.get("drift_detected") is not True:
                    active_tx = state.get("active_tx")
                    if isinstance(active_tx, dict):
                        active_tx["tx_id"] = context["tx_id"]
                        active_tx["ticket_id"] = context["ticket_id"]
                        active_tx["status"] = phase
                        active_tx["phase"] = phase
                        active_tx["current_step"] = step_id
                        if isinstance(context.get("session_id"), str):
                            active_tx["session_id"] = context["session_id"]
                    return self.state_store.tx_event_append_and_state_save(
                        tx_id=context["tx_id"],
                        ticket_id=context["ticket_id"],
                        event_type=event_type,
                        phase=phase,
                        step_id=step_id,
                        actor=actor,
                        session_id=context["session_id"],
                        payload=payload,
                        state=state,
                    )

        event = self.state_store.tx_event_append(
            tx_id=context["tx_id"],
            ticket_id=context["ticket_id"],
            event_type=event_type,
            phase=phase,
            step_id=step_id,
            actor=actor,
            session_id=context["session_id"],
            payload=payload,
        )
        rebuild_fn = getattr(self.state_rebuilder, "rebuild_tx_state", None)
        if callable(rebuild_fn):
            rebuild = rebuild_fn()
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
            return {
                "tx_status": "",
                "tx_phase": "",
                "next_action": "",
                "terminal": False,
                "requires_followup": False,
                "followup_tool": None,
            }

        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            return {
                "tx_status": "",
                "tx_phase": "",
                "next_action": "",
                "terminal": False,
                "requires_followup": False,
                "followup_tool": None,
            }

        guidance = build_guidance_from_active_tx(active_tx)
        return {
            "tx_status": guidance["canonical_status"],
            "tx_phase": guidance["canonical_phase"],
            "next_action": guidance["next_action"],
            "terminal": guidance["terminal"],
            "requires_followup": guidance["requires_followup"],
            "followup_tool": guidance["followup_tool"],
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
                str(
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
                    str(
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
