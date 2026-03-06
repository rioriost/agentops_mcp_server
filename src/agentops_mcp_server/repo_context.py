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
    "snapshot": "snapshot.json",
    "checkpoint": "checkpoint.json",
}

STATE_ARTIFACT_FILES = {
    **CANONICAL_ARTIFACT_FILES,
    **DERIVED_ARTIFACT_FILES,
}


class RepoContext:
    def __init__(self, root: Optional[Path] = None) -> None:
        resolved_root = root or Path.cwd().resolve()
        self.set_repo_root(resolved_root)

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

    def resolve_workspace_root(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()

        repo_root = self.repo_root
        if candidate in {Path("."), Path(repo_root.name)}:
            return repo_root

        parent_candidate = (repo_root.parent / candidate).resolve()
        if parent_candidate.exists():
            return parent_candidate

        cwd = Path.cwd().resolve()
        if candidate in {Path("."), Path(cwd.name)}:
            return cwd
        return (cwd / candidate).resolve()

    def set_repo_root(self, root: Path) -> None:
        self.repo_root = root
        self.journal = self.legacy_artifact_path("journal", root)
        self.snapshot = self.legacy_artifact_path("snapshot", root)
        self.checkpoint = self.legacy_artifact_path("checkpoint", root)
        self.handoff = self.state_artifact_path("handoff", root)
        self.observability = self.state_artifact_path("observability", root)
        self.tx_event_log = self.state_artifact_path("tx_event_log", root)
        self.tx_state = self.state_artifact_path("tx_state", root)
        self.verify = self.repo_root / ".zed" / "scripts" / "verify"

    def get_repo_root(self) -> Path:
        return self.repo_root
