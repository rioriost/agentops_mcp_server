from __future__ import annotations

from pathlib import Path
from typing import Optional

CANONICAL_ARTIFACT_FILES = {
    "tx_event_log": "tx_event_log.jsonl",
    "tx_state": "tx_state.json",
}

DERIVED_ARTIFACT_FILES = {
    "handoff": "handoff.json",
    "observability": "observability_summary.json",
}

RUNTIME_ARTIFACT_FILES = {
    "errors": "errors.jsonl",
}

LEGACY_ARTIFACT_FILES = {
    "journal": "journal.jsonl",
}

STATE_ARTIFACT_FILES = {
    **CANONICAL_ARTIFACT_FILES,
    **DERIVED_ARTIFACT_FILES,
    **RUNTIME_ARTIFACT_FILES,
}


class RepoContext:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.repo_root: Optional[Path] = None
        self.journal: Optional[Path] = None
        self.handoff: Optional[Path] = None
        self.observability: Optional[Path] = None
        self.tx_event_log: Optional[Path] = None
        self.tx_state: Optional[Path] = None
        self.errors: Optional[Path] = None
        self.verify: Optional[Path] = None

        resolved_root = (
            root.resolve() if isinstance(root, Path) else Path.cwd().resolve()
        )
        if resolved_root != Path("/"):
            self.set_repo_root(resolved_root)

    def _validate_repo_root(self, root: Path) -> Path:
        resolved_root = root.resolve()
        if resolved_root == Path("/"):
            raise ValueError(
                "repo_root cannot be '/' (call workspace_initialize(cwd) with a project directory)"
            )
        return resolved_root

    def has_repo_root(self) -> bool:
        return self.repo_root is not None

    def require_repo_root(self) -> Path:
        if self.repo_root is None:
            raise ValueError(
                "project root is not initialized; call workspace_initialize(cwd) before using file-backed tools"
            )
        return self.repo_root

    def bind_repo_root(self, root: Path) -> dict[str, object]:
        resolved_root = self._validate_repo_root(root)
        current_root = self.repo_root

        if current_root is None:
            self._apply_repo_root(resolved_root)
            return {
                "ok": True,
                "repo_root": str(resolved_root),
                "initialized": True,
                "changed": True,
            }

        if current_root == resolved_root:
            return {
                "ok": True,
                "repo_root": str(resolved_root),
                "initialized": True,
                "changed": False,
            }

        raise ValueError(
            f"repo_root is already initialized: {current_root} (cannot rebind to {resolved_root})"
        )

    def state_artifact_path(self, kind: str, root: Optional[Path] = None) -> Path:
        resolved_root = (
            self._validate_repo_root(root)
            if root is not None
            else self.require_repo_root()
        )
        filename = STATE_ARTIFACT_FILES.get(kind)
        if not filename:
            raise ValueError(f"unknown state artifact: {kind}")
        return resolved_root / ".agent" / filename

    def legacy_artifact_path(self, kind: str, root: Optional[Path] = None) -> Path:
        resolved_root = (
            self._validate_repo_root(root)
            if root is not None
            else self.require_repo_root()
        )
        filename = LEGACY_ARTIFACT_FILES.get(kind)
        if not filename:
            raise ValueError(f"unknown legacy artifact: {kind}")
        return resolved_root / ".agent" / filename

    def _apply_repo_root(self, root: Path) -> None:
        self.repo_root = root
        self.journal = self.legacy_artifact_path("journal", root)
        self.handoff = self.state_artifact_path("handoff", root)
        self.observability = self.state_artifact_path("observability", root)
        self.tx_event_log = self.state_artifact_path("tx_event_log", root)
        self.tx_state = self.state_artifact_path("tx_state", root)
        self.errors = self.state_artifact_path("errors", root)
        self.verify = root / ".zed" / "scripts" / "verify"

    def set_repo_root(self, root: Path) -> None:
        resolved_root = self._validate_repo_root(root)
        self._apply_repo_root(resolved_root)

    def get_repo_root(self) -> Path:
        return self.require_repo_root()
