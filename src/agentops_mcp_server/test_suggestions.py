from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .git_repo import GitRepo
from .repo_context import RepoContext

CODE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
}


def unique_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def extract_artifact_paths(events: List[Dict[str, Any]]) -> List[str]:
    paths: List[str] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        for key in ("path", "file"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
        for key in ("paths", "files"):
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        paths.append(item.strip())
    return unique_preserve_order(paths)


def is_test_path(path: str) -> bool:
    return (
        "/tests/" in path
        or path.startswith("tests/")
        or "/test/" in path
        or path.startswith("test/")
        or "/__tests__/" in path
        or path.startswith("__tests__/")
    )


def normalize_test_candidate(path: str, suffix: str) -> str:
    if not suffix:
        return path
    if re.search(r"(?:^|/)(test_.*|.*_test)" + re.escape(suffix) + r"$", path):
        return path
    if is_test_path(path):
        return re.sub(rf"{re.escape(suffix)}$", rf"_test{suffix}", path)
    return path


def candidates_for_path(path: str) -> List[str]:
    if is_test_path(path):
        return [path]

    p = Path(path)
    suffixes = p.suffixes
    if not suffixes or not any(s in CODE_SUFFIXES for s in suffixes):
        return []

    suffix = "".join(suffixes)
    stem = p.name[: -len(suffix)] if suffix else p.name
    candidates: List[str] = []

    candidates.append(str(p.with_name(f"{stem}_test{suffix}")))
    candidates.append(str(p.with_name(f"test_{stem}{suffix}")))

    if "/src/" in path:
        candidates.append(path.replace("/src/", "/tests/"))
        candidates.append(path.replace("/src/", "/test/"))
        candidates.append(path.replace("/src/", "/__tests__/"))
    elif path.startswith("src/"):
        candidates.append(path.replace("src/", "tests/", 1))
        candidates.append(path.replace("src/", "test/", 1))
        candidates.append(path.replace("src/", "__tests__/", 1))

    for marker in ("/lib/", "/app/", "/pkg/"):
        if marker in path:
            candidates.append(path.replace(marker, "/tests/"))
            candidates.append(path.replace(marker, "/test/"))

    normalized = [normalize_test_candidate(c, suffix) for c in candidates]
    return unique_preserve_order(normalized)


def parse_changed_files(diff: str) -> List[str]:
    if "diff --git " in diff:
        changed_files: List[str] = []
        for line in diff.splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split()
            if len(parts) >= 4:
                path = parts[2]
                if path.startswith("a/"):
                    path = path[2:]
                changed_files.append(path)
        return changed_files
    return [line.strip() for line in diff.splitlines() if line.strip()]


class TestSuggester:
    __test__ = False

    def __init__(self, git_repo: GitRepo, repo_context: RepoContext) -> None:
        self.git_repo = git_repo
        self.repo_context = repo_context

    def tests_suggest(
        self, diff: Optional[str] = None, failures: Optional[str] = None
    ) -> Dict[str, Any]:
        if diff is None:
            diff = "\n".join(
                line
                for line in [
                    self.git_repo.git("diff", "--name-only"),
                    self.git_repo.git("diff", "--name-only", "--cached"),
                ]
                if line
            )

        suggestions: List[Dict[str, str]] = []
        seen_paths: set[str] = set()

        def _add(path: str, reason: str) -> None:
            if path in seen_paths:
                return
            seen_paths.add(path)
            suggestions.append({"path": path, "reason": reason})

        changed_files = parse_changed_files(diff)

        for path in changed_files:
            candidates = candidates_for_path(path)
            if not candidates:
                continue
            if is_test_path(path):
                for candidate in candidates:
                    _add(candidate, "existing test changed")
            else:
                for candidate in candidates:
                    _add(candidate, f"covers {path}")

        if failures:
            _add("(investigate)", "verify failures present")

        if not suggestions:
            suggestions.append({"path": "(none)", "reason": "no obvious test targets"})

        return {"suggestions": suggestions}

    def tests_suggest_from_failures(self, log_path: str) -> Dict[str, Any]:
        if not log_path:
            raise ValueError("log_path is required")
        path = Path(log_path)
        if not path.is_absolute():
            path = self.repo_context.get_repo_root() / log_path
        if not path.exists():
            raise FileNotFoundError(f"log not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return self.tests_suggest(failures=content)
