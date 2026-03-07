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

LEGACY_ARTIFACT_FILES = {
    "journal": "journal.jsonl",
}

STATE_ARTIFACT_FILES = {
    **CANONICAL_ARTIFACT_FILES,
    **DERIVED_ARTIFACT_FILES,
}


class RepoContext:
    def __init__(self, root: Optional[Path] = None) -> None:
        resolved_root = root or Path.cwd()
        self.set_repo_root(resolved_root)

    def _validate_repo_root(self, root: Path) -> Path:
        resolved_root = root.resolve()
        if resolved_root == Path("/"):
            raise ValueError(
                "repo_root cannot be '/' (launch the MCP server from a project directory)"
            )
        return resolved_root

    def state_artifact_path(self, kind: str, root: Optional[Path] = None) -> Path:
        resolved_root = root or self.repo_root
        filename = STATE_ARTIFACT_FILES.get(kind)
        if not filename:
            raise ValueError(f"unknown state artifact: {kind}")
        return resolved_root / ".agent" / filename

    def legacy_artifact_path(self, kind: str, root: Optional[Path] = None) -> Path:
        resolved_root = root or self.repo_root
        filename = LEGACY_ARTIFACT_FILES.get(kind)
        if not filename:
            raise ValueError(f"unknown legacy artifact: {kind}")
        return resolved_root / ".agent" / filename

    def set_repo_root(self, root: Path) -> None:
        resolved_root = self._validate_repo_root(root)
        self.repo_root = resolved_root
        self.journal = self.legacy_artifact_path("journal", resolved_root)
        self.handoff = self.state_artifact_path("handoff", resolved_root)
        self.observability = self.state_artifact_path("observability", resolved_root)
        self.tx_event_log = self.state_artifact_path("tx_event_log", resolved_root)
        self.tx_state = self.state_artifact_path("tx_state", resolved_root)
        self.verify = self.repo_root / ".zed" / "scripts" / "verify"

    def get_repo_root(self) -> Path:
        return self.repo_root
