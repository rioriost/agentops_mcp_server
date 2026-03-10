from __future__ import annotations

from typing import Any, Dict, Optional

from .git_repo import GitRepo
from .test_suggestions import CODE_SUFFIXES, is_test_path, parse_changed_files
from .verify_runner import VerifyRunner
from .workflow_response import build_success_response


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

    def _load_tx_context(self) -> Optional[Dict[str, Any]]:
        if self.state_store is None:
            return None
        tx_state = self.state_store.read_json_file(
            self.state_store.repo_context.tx_state
        )
        if not isinstance(tx_state, dict):
            return None
        active_tx = tx_state.get("active_tx")
        if not isinstance(active_tx, dict):
            return None

        tx_id = active_tx.get("tx_id")
        ticket_id = active_tx.get("ticket_id")
        session_id = active_tx.get("session_id")
        phase = active_tx.get("phase") or "in-progress"
        step_id = active_tx.get("current_step") or "verify"

        if isinstance(tx_id, bool) or not isinstance(tx_id, int):
            return None
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            return None
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        if not isinstance(phase, str) or not phase.strip():
            phase = "in-progress"
        if not isinstance(step_id, str) or not step_id.strip():
            step_id = "verify"

        return {
            "tx_id": tx_id,
            "ticket_id": ticket_id.strip(),
            "session_id": session_id.strip(),
            "phase": phase.strip(),
            "step_id": step_id.strip(),
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

        phase = phase_override or context["phase"]
        step_id = step_id_override or context["step_id"]
        actor = {"tool": "repo_tools"}

        tx_state = self.state_store.read_json_file(
            self.state_store.repo_context.tx_state
        )
        if isinstance(tx_state, dict):
            active_tx = tx_state.get("active_tx")
            if isinstance(active_tx, dict):
                active_tx["tx_id"] = context["tx_id"]
                active_tx["ticket_id"] = context["ticket_id"]
                active_tx["phase"] = phase
                active_tx["current_step"] = step_id
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

        if self.state_rebuilder is not None:
            rebuild = self.state_rebuilder.rebuild_tx_state()
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
                        active_tx["phase"] = phase
                        active_tx["current_step"] = step_id
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
        if self.state_store is None:
            response = build_success_response(
                tx_state={
                    "active_tx": None,
                    "status": None,
                    "next_action": "tx.begin",
                    "verify_state": None,
                    "commit_state": None,
                    "semantic_summary": None,
                    "integrity": {},
                }
            )
        else:
            tx_state = self.state_store.read_json_file(
                self.state_store.repo_context.tx_state
            )
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

    def repo_verify(self, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
        context = self._load_tx_context()
        if context is None or self.state_store is None:
            result = self.verify_runner.run_verify(timeout_sec=timeout_sec)
            result.update(self._workflow_guidance())
            return result

        active_tx = self.state_store.read_json_file(
            self.state_store.repo_context.tx_state
        )
        active = active_tx.get("active_tx") if isinstance(active_tx, dict) else {}
        if isinstance(active, dict):
            status = active.get("status")
            if isinstance(status, str) and status.strip() in {"done", "blocked"}:
                raise ValueError("cannot verify a terminal transaction")

        self._emit_tx_event(
            event_type="tx.verify.start",
            payload={"command": str(self.state_store.repo_context.verify)},
            phase_override="checking",
            step_id_override=context["step_id"],
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
                step_id_override=context["step_id"],
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
                step_id_override=context["step_id"],
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
