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

    def _auto_snapshot_checkpoint_after_commit(self) -> Dict[str, Any]:
        if not self.repo_context.journal.exists():
            return {
                "ok": False,
                "reason": "journal not found",
                "path": str(self.repo_context.journal),
            }

        snapshot = self.state_store.read_json_file(self.repo_context.snapshot)
        snapshot_state = snapshot.get("state") if isinstance(snapshot, dict) else None
        snapshot_session_id: Optional[str] = None
        snapshot_last_seq: Optional[int] = None

        if isinstance(snapshot, dict):
            snapshot_session_id = snapshot.get("session_id")
            if not isinstance(snapshot_session_id, str):
                snapshot_session_id = None
            snapshot_last_seq = snapshot.get("last_applied_seq")
            if not isinstance(snapshot_last_seq, int):
                snapshot_last_seq = None

        if not snapshot_session_id and isinstance(snapshot_state, dict):
            state_session_id = snapshot_state.get("session_id")
            if isinstance(state_session_id, str):
                snapshot_session_id = state_session_id

        start_seq = snapshot_last_seq or 0
        journal_result = self.state_rebuilder.read_journal_events(start_seq=start_seq)
        events = journal_result.get("events") or []
        invalid_lines = (
            journal_result.get("invalid_lines")
            if isinstance(journal_result.get("invalid_lines"), int)
            else 0
        )
        last_seq = journal_result.get("last_seq")
        if not isinstance(last_seq, int):
            last_seq = start_seq

        if not events and snapshot is None and last_seq == 0:
            return {"ok": False, "reason": "no journal events", "last_seq": last_seq}

        state = self.state_rebuilder.replay_events_to_state(
            snapshot_state=snapshot_state,
            events=events,
            preferred_session_id=snapshot_session_id,
            invalid_lines=invalid_lines,
        )
        session_id = snapshot_session_id
        if not session_id and isinstance(state, dict):
            state_session_id = state.get("session_id")
            if isinstance(state_session_id, str):
                session_id = state_session_id

        snapshot_result = self.state_store.snapshot_save(
            state=state, session_id=session_id, last_applied_seq=last_seq
        )
        checkpoint_result = self.state_store.checkpoint_update(
            last_applied_seq=last_seq, snapshot_path=self.repo_context.snapshot.name
        )
        rotation_result = self.state_rebuilder.rotate_journal_if_prev_week()
        if rotation_result.get("rotated"):
            self.state_store.journal_safe("journal.rotate", rotation_result)
        return {
            "ok": True,
            "snapshot": snapshot_result,
            "checkpoint": checkpoint_result,
            "journal_rotation": rotation_result,
            "last_applied_seq": last_seq,
            "events_applied": len(events),
        }

    def _post_commit_snapshot_checkpoint(self) -> None:
        try:
            auto_result = self._auto_snapshot_checkpoint_after_commit()
            if not auto_result.get("ok"):
                self.state_store.journal_safe(
                    "error",
                    {
                        "message": "auto snapshot/checkpoint skipped",
                        "context": auto_result,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            self.state_store.journal_safe(
                "error",
                {"message": "auto snapshot/checkpoint failed", "context": str(exc)},
            )

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
            self.state_store.journal_safe(
                "commit.end", {"ok": False, "summary": str(exc)}
            )
            raise
        self.state_store.journal_safe(
            "commit.end", {"ok": True, "sha": sha, "summary": summary}
        )
        self._post_commit_snapshot_checkpoint()
        return sha, summary

    def commit_if_verified(
        self, message: str, timeout_sec: Optional[int] = None
    ) -> Dict[str, str]:
        verify_result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
        if not verify_result["ok"]:
            raise RuntimeError(
                f"verify failed (code={verify_result['returncode']}): {verify_result['stderr']}"
            )
        self.state_store.journal_safe(
            "commit.start", {"message": message, "files": "auto"}
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
            verify_result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
            if not verify_result["ok"]:
                stderr = (verify_result.get("stderr") or "").strip()
                stdout = (verify_result.get("stdout") or "").strip()
                details = stderr or stdout or "unknown error"
                raise RuntimeError(
                    f"verify failed (code={verify_result['returncode']}): {details}"
                )

        self.state_store.journal_safe(
            "commit.start", {"message": message, "files": files}
        )
        status_lines = self.git_repo.status_porcelain()
        if not status_lines:
            self.state_store.journal_safe(
                "commit.end", {"ok": False, "summary": "no changes to commit"}
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
                self.state_store.journal_safe(
                    "commit.end", {"ok": False, "summary": "no files specified"}
                )
                return {"ok": False, "reason": "no files specified"}
            self.git_repo.git("add", *paths)

        msg = (message or "").strip().replace("\n", " ")
        if not msg:
            msg = self._commit_message_from_status(status_lines)
        msg = self._normalize_commit_message(msg)

        sha, summary = self._run_git_commit(msg)
        return {"ok": True, "sha": sha, "message": msg, "summary": summary}
