from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

from .repo_context import RepoContext
from .state_store import StateStore


def _truncate_text(value: Optional[str], limit: int = 2000) -> Optional[str]:
    if value is None:
        return None
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    suffix = "...(truncated)"
    prefix = value[:limit].rstrip()
    return prefix + suffix


class VerifyRunner:
    def __init__(self, repo_context: RepoContext, state_store: StateStore) -> None:
        self.repo_context = repo_context
        self.state_store = state_store

    def run_verify(self, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
        if not self.repo_context.verify.exists():
            raise FileNotFoundError(
                f"verify script not found: {self.repo_context.verify}"
            )
        self.state_store.journal_safe(
            "verify.start",
            {"command": str(self.repo_context.verify), "timeout_sec": timeout_sec},
        )
        try:
            result = subprocess.run(
                [str(self.repo_context.verify)],
                cwd=str(self.repo_context.get_repo_root()),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip()
            payload = {
                "ok": False,
                "returncode": None,
                "stdout": stdout,
                "stderr": f"verify timed out after {timeout_sec}s",
            }
            journal_payload = {
                "ok": False,
                "returncode": None,
                "stdout": _truncate_text(stdout),
                "stderr": payload["stderr"],
            }
            self.state_store.journal_safe("verify.end", journal_payload)
            return payload

        payload = {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        journal_payload = {
            "ok": payload["ok"],
            "returncode": payload["returncode"],
            "stdout": _truncate_text(payload["stdout"]),
            "stderr": _truncate_text(payload["stderr"]),
        }
        self.state_store.journal_safe("verify.end", journal_payload)
        return payload
