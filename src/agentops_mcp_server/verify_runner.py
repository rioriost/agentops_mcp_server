from __future__ import annotations

import subprocess
from typing import Any, Dict, Optional

from .repo_context import RepoContext
from .state_store import StateStore


class VerifyRunner:
    def __init__(self, repo_context: RepoContext, state_store: StateStore) -> None:
        self.repo_context = repo_context
        self.state_store = state_store

    def run_verify(self, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
        if not self.repo_context.verify.exists():
            raise FileNotFoundError(
                f"verify script not found: {self.repo_context.verify}"
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

            return payload

        payload = {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        return payload
