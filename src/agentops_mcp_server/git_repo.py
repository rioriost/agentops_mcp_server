from __future__ import annotations

import subprocess
from typing import List

from .repo_context import RepoContext


class GitRepo:
    def __init__(self, repo_context: RepoContext) -> None:
        self.repo_context = repo_context

    def git(self, *args: str) -> str:
        try:
            out = subprocess.check_output(
                ["git", *args],
                cwd=str(self.repo_context.get_repo_root()),
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("git is not installed or not in PATH") from exc
        except subprocess.CalledProcessError as exc:
            output = exc.output
            if isinstance(output, bytes):
                output_text = output.decode("utf-8", errors="replace").strip()
            else:
                output_text = str(output).strip()
            raise RuntimeError(output_text) from exc
        return out.decode("utf-8", errors="replace").strip()

    def status_porcelain(self) -> List[str]:
        out = self.git("status", "--porcelain")
        if not out:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def diff_stat(self) -> str:
        return self.git("diff", "--stat")

    def diff_stat_cached(self) -> str:
        return self.git("diff", "--stat", "--cached")
