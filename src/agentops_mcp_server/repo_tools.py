from __future__ import annotations

from typing import Any, Dict, List, Optional

from .git_repo import GitRepo
from .test_suggestions import CODE_SUFFIXES, is_test_path, parse_changed_files
from .verify_runner import VerifyRunner


class RepoTools:
    def __init__(self, git_repo: GitRepo, verify_runner: VerifyRunner) -> None:
        self.git_repo = git_repo
        self.verify_runner = verify_runner

    def repo_verify(self, timeout_sec: Optional[int] = None) -> Dict[str, Any]:
        return self.verify_runner.run_verify(timeout_sec=timeout_sec)

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
            context["verify"] = self.verify_runner.run_verify()
        return context
