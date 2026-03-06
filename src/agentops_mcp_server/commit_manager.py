from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .git_repo import GitRepo
from .state_rebuilder import StateRebuilder
from .state_store import StateStore
from .verify_runner import VerifyRunner


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
        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "phase": phase,
            "step_id": step_id,
        }

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
        event = self.state_store.tx_event_append(
            tx_id=context["tx_id"],
            ticket_id=context["ticket_id"],
            event_type=event_type,
            phase=phase,
            step_id=step_id,
            actor=actor,
            session_id=context.get("session_id", "unknown"),
            payload=payload,
        )
        rebuild = self.state_rebuilder.rebuild_tx_state()
        if rebuild.get("ok") and isinstance(rebuild.get("state"), dict):
            self.state_store.tx_state_save(rebuild["state"])
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

    def _run_git_commit(self, message: str) -> Tuple[str, str]:
        summary = self.git_repo.diff_stat_cached()
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
            payload={"sha": sha, "summary": summary},
            phase_override="committed",
        )
        return sha, summary

    def commit_if_verified(
        self, message: str, timeout_sec: Optional[int] = None
    ) -> Dict[str, str]:
        self._emit_tx_event(
            event_type="tx.verify.start",
            payload={"command": str(self.repo_context.verify)},
            phase_override="checking",
        )
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
                f"verify failed (code={verify_result['returncode']}): {verify_result['stderr']}"
            )
        self._emit_tx_event(
            event_type="tx.verify.pass",
            payload={
                "ok": True,
                "returncode": verify_result.get("returncode"),
                "summary": verify_result.get("stdout") or "verify passed",
            },
            phase_override="checking",
        )
        self._emit_tx_event(
            event_type="tx.commit.start",
            payload={"message": message, "files": "auto"},
            phase_override="verified",
        )
        self.git_repo.git("add", "-A")

        msg = self._normalize_commit_message(message)
        sha, _summary = self._run_git_commit(msg)
        return {"sha": sha, "message": msg}

    def repo_commit(
        self,
        message: Optional[str] = None,
        files: Optional[str] = "auto",
        run_verify: Optional[bool] = None,
        timeout_sec: Optional[int] = None,
    ) -> Dict[str, Any]:
        if run_verify:
            self._emit_tx_event(
                event_type="tx.verify.start",
                payload={"command": str(self.repo_context.verify)},
                phase_override="checking",
            )
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
                    f"verify failed (code={verify_result['returncode']}): {details}"
                )
            self._emit_tx_event(
                event_type="tx.verify.pass",
                payload={
                    "ok": True,
                    "returncode": verify_result.get("returncode"),
                    "summary": verify_result.get("stdout") or "verify passed",
                },
                phase_override="checking",
            )

        self._emit_tx_event(
            event_type="tx.commit.start",
            payload={"message": message, "files": files},
            phase_override="verified",
        )
        status_lines = self.git_repo.status_porcelain()
        if not status_lines:
            self._emit_tx_event(
                event_type="tx.commit.fail",
                payload={
                    "error": "no changes to commit",
                    "summary": "no changes to commit",
                },
                phase_override="verified",
            )
            return {"ok": False, "reason": "no changes to commit"}

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
                return {"ok": False, "reason": "no files specified"}
            self.git_repo.git("add", *paths)

        msg = (message or "").strip().replace("\n", " ")
        if not msg:
            msg = self._commit_message_from_status(status_lines)
        msg = self._normalize_commit_message(msg)

        sha, summary = self._run_git_commit(msg)
        return {"ok": True, "sha": sha, "message": msg, "summary": summary}
