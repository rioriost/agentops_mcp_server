from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .git_repo import GitRepo
from .test_suggestions import CODE_SUFFIXES, is_test_path, parse_changed_files
from .verify_runner import VerifyRunner
from .workflow_response import (
    build_resume_load_value_error_adapter,
    build_success_response,
    canonical_idle_baseline,
    is_valid_exact_resume_tx_state,
    load_resume_state_shared,
)


class RepoTools:
    def __init__(
        self,
        git_repo: GitRepo,
        verify_runner: VerifyRunner,
        state_store: Any | None = None,
        state_rebuilder: Any | None = None,
    ) -> None:
        self.git_repo = git_repo
        self.verify_runner = verify_runner
        self.state_store = state_store
        self.state_rebuilder = state_rebuilder

    def _apply_verify_event_state(
        self,
        *,
        active_tx: Dict[str, Any],
        event_type: str,
        payload: Dict[str, Any],
        phase: str,
        step_id: str,
        session_id: str,
        tx_id: int,
        ticket_id: str,
    ) -> None:
        active_tx["tx_id"] = tx_id
        active_tx["ticket_id"] = ticket_id
        active_tx["session_id"] = session_id

        if event_type == "tx.verify.start":
            active_tx["status"] = "checking"
            active_tx["phase"] = "checking"
            active_tx["current_step"] = step_id
            active_tx["verify_state"] = {
                "status": "running",
                "last_result": payload,
            }
            active_tx["next_action"] = "tx.verify.pass"
        elif event_type == "tx.verify.pass":
            active_tx["status"] = "verified"
            active_tx["phase"] = "verified"
            active_tx["current_step"] = step_id
            active_tx["verify_state"] = {
                "status": "passed",
                "last_result": payload,
            }
            active_tx["semantic_summary"] = "Verification passed"
            active_tx["next_action"] = "tx.commit.start"
        elif event_type == "tx.verify.fail":
            active_tx["status"] = "checking"
            active_tx["phase"] = "checking"
            active_tx["current_step"] = step_id
            active_tx["verify_state"] = {
                "status": "failed",
                "last_result": payload,
            }
            active_tx["semantic_summary"] = "Verification failed"
            active_tx["next_action"] = "fix and re-verify"

    def _is_valid_materialized_tx_state(self, tx_state: Any) -> bool:
        return is_valid_exact_resume_tx_state(tx_state)

    def _load_resume_state(self) -> Dict[str, Any]:
        baseline = canonical_idle_baseline()
        if self.state_store is None:
            return baseline

        return load_resume_state_shared(
            read_tx_state=lambda: self.state_store.read_json_file(
                self.state_store.repo_context.tx_state
            ),
            rebuild_tx_state=(
                self.state_rebuilder.rebuild_tx_state
                if self.state_rebuilder is not None
                else lambda: {"ok": False}
            ),
            is_valid_tx_state=self._is_valid_materialized_tx_state,
            baseline=baseline,
            rebuild_when_invalid=True,
            **build_resume_load_value_error_adapter(),
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
        session_id = active_tx.get("session_id")
        next_action = tx_state.get("next_action")

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
            "session_id": resolved_session_id,
            "next_action": next_action.strip(),
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
        if not context or self.state_store is None:
            return None

        phase = phase_override or context["next_action"]
        step_id = step_id_override or "verify"
        actor = {"tool": "repo_tools"}

        tx_state = self._load_resume_state()
        active_tx = tx_state.get("active_tx")
        if isinstance(active_tx, dict):
            self._apply_verify_event_state(
                active_tx=active_tx,
                event_type=event_type,
                payload=payload,
                phase=phase,
                step_id=step_id,
                session_id=context["session_id"],
                tx_id=context["tx_id"],
                ticket_id=context["ticket_id"],
            )
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

    def _workflow_guidance(self) -> Dict[str, Any]:
        tx_state = self._load_resume_state()
        response = build_success_response(tx_state=tx_state)

        active_tx = tx_state.get("active_tx") if isinstance(tx_state, dict) else None
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

    def repo_verify(self, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
        context = self._load_tx_context()
        if context is None or self.state_store is None:
            result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
            result.update(self._workflow_guidance())
            return result

        tx_state = self._load_resume_state()
        canonical_status = (
            tx_state.get("status") if isinstance(tx_state, dict) else None
        )
        canonical_next_action = (
            tx_state.get("next_action") if isinstance(tx_state, dict) else None
        )
        if isinstance(canonical_status, str) and canonical_status.strip() in {
            "done",
            "blocked",
        }:
            raise ValueError(
                json.dumps(
                    build_failure_response(
                        error_code="terminal_transaction",
                        reason="cannot verify a terminal transaction",
                        tx_state=tx_state,
                        recommended_next_tool="ops_start_task",
                        recommended_action="Do not resume post-terminal work; begin a new transaction only when canonical state allows it.",
                    ),
                    ensure_ascii=False,
                )
            )
        if (
            not isinstance(canonical_next_action, str)
            or not canonical_next_action.strip()
        ):
            raise ValueError(
                json.dumps(
                    build_failure_response(
                        error_code="invalid_ordering",
                        reason="cannot verify without a canonical next_action",
                        tx_state=tx_state,
                        recommended_next_tool="ops_capture_state",
                        recommended_action="Restore the exact active transaction with a valid top-level next_action before running verification.",
                    ),
                    ensure_ascii=False,
                )
            )

        self._emit_tx_event(
            event_type="tx.verify.start",
            payload={"command": str(self.state_store.repo_context.verify)},
            phase_override="checking",
        )

        result = self.verify_runner.run_verify(timeout_sec=timeout_sec)

        if result.get("ok"):
            self._emit_tx_event(
                event_type="tx.verify.pass",
                payload={
                    "ok": True,
                    "returncode": result.get("returncode"),
                    "summary": result.get("stdout") or "verify passed",
                },
                phase_override="verified",
            )
        else:
            details = (
                (result.get("stderr") or "").strip()
                or (result.get("stdout") or "").strip()
                or "verify failed"
            )
            self._emit_tx_event(
                event_type="tx.verify.fail",
                payload={
                    "ok": False,
                    "returncode": result.get("returncode"),
                    "error": details,
                },
                phase_override="checking",
            )

        result.update(self._workflow_guidance())
        return result

    def repo_status_summary(self) -> Dict[str, Any]:
        return {
            "branch": self.git_repo.git("rev-parse", "--abbrev-ref", "HEAD"),
            "status": self.git_repo.git("status", "--short"),
            "diff": self.git_repo.diff_stat(),
            "staged_diff": self.git_repo.diff_stat_cached(),
            "last_commit": self.git_repo.git("log", "-1", "--oneline"),
            "files": {
                "unstaged": self.git_repo.git("diff", "--name-only"),
                "staged": self.git_repo.git("diff", "--name-only", "--cached"),
            },
        }

    def repo_commit_message_suggest(self, diff: Optional[str] = None) -> Dict[str, Any]:
        if diff is None:
            diff_stat = self.git_repo.diff_stat_cached() or self.git_repo.diff_stat()
            files_blob = "\n".join(
                line
                for line in [
                    self.git_repo.git("diff", "--name-only", "--cached"),
                    self.git_repo.git("diff", "--name-only"),
                ]
                if line
            )
            file_list = parse_changed_files(files_blob)
        else:
            diff_stat = diff
            file_list = parse_changed_files(diff)

        def _is_code_path(path: str) -> bool:
            return any(path.endswith(ext) for ext in CODE_SUFFIXES)

        has_docs = any(
            path.startswith("docs/") or path.endswith(".md") for path in file_list
        )
        has_tests = any(is_test_path(path) for path in file_list)
        has_code = any(_is_code_path(path) for path in file_list)
        has_config = any(
            path.endswith((".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock"))
            for path in file_list
        )

        if has_docs and not has_code and not has_tests:
            prefix = "docs"
        elif has_tests and not has_code:
            prefix = "test"
        elif has_code:
            prefix = "feat"
        elif has_config:
            prefix = "chore"
        else:
            prefix = "chore"

        suggestions = [
            f"{prefix}: update changes",
            f"{prefix}: adjust files",
            f"{prefix}: refresh repo",
        ]
        return {"suggestions": suggestions, "diff": diff_stat, "files": file_list}

    def session_capture_context(
        self, run_verify: bool = False, log: bool = False
    ) -> Dict[str, Any]:
        context = {
            "branch": self.git_repo.git("rev-parse", "--abbrev-ref", "HEAD"),
            "status": self.git_repo.git("status", "--short"),
            "diff": self.git_repo.diff_stat(),
            "staged_diff": self.git_repo.diff_stat_cached(),
            "last_commit": self.git_repo.git("log", "-1", "--oneline"),
            "files": {
                "unstaged": self.git_repo.git("diff", "--name-only"),
                "staged": self.git_repo.git("diff", "--name-only", "--cached"),
            },
        }

        if run_verify:
            context["verify"] = self.repo_verify()
        return context
