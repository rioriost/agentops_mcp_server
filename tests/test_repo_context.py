from pathlib import Path

import pytest

from agentops_mcp_server.repo_context import RepoContext


def test_state_artifact_path_invalid_kind(repo_context):
    with pytest.raises(ValueError, match="unknown state artifact"):
        repo_context.state_artifact_path("nope")


def test_set_repo_root_updates_artifacts(tmp_path):
    context = RepoContext(tmp_path)
    new_root = tmp_path / "other"
    new_root.mkdir()
    context.set_repo_root(new_root)
    assert context.get_repo_root() == new_root
    assert context.journal == new_root / ".agent" / "journal.jsonl"
    assert context.handoff == new_root / ".agent" / "handoff.json"
    assert context.observability == new_root / ".agent" / "observability_summary.json"
    assert context.tx_event_log == new_root / ".agent" / "tx_event_log.jsonl"
    assert context.tx_state == new_root / ".agent" / "tx_state.json"


def test_legacy_artifact_path_invalid_kind(repo_context):
    with pytest.raises(ValueError, match="unknown legacy artifact"):
        repo_context.legacy_artifact_path("nope")


def test_state_artifact_path_known_kind(repo_context):
    path = repo_context.state_artifact_path("tx_state")
    assert path.name == "tx_state.json"
    assert path.parent.name == ".agent"


def test_repo_context_rejects_root_path():
    with pytest.raises(ValueError, match="repo_root cannot be '/'"):
        RepoContext(Path("/"))
