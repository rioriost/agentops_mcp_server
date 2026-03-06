import pytest

from agentops_mcp_server.repo_context import RepoContext


def test_state_artifact_path_invalid_kind(repo_context):
    with pytest.raises(ValueError, match="unknown state artifact"):
        repo_context.state_artifact_path("nope")


def test_resolve_workspace_root_absolute(tmp_path):
    context = RepoContext(tmp_path)
    resolved = context.resolve_workspace_root(str(tmp_path))
    assert resolved == tmp_path.resolve()


def test_resolve_workspace_root_relative_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = RepoContext(tmp_path)
    resolved = context.resolve_workspace_root(tmp_path.name)
    assert resolved == tmp_path.resolve()


def test_resolve_workspace_root_prefers_repo_root_name(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    other_root = tmp_path / "other"
    other_root.mkdir()

    monkeypatch.chdir(other_root)
    context = RepoContext(repo_root)
    resolved = context.resolve_workspace_root(repo_root.name)

    assert resolved == repo_root.resolve()


def test_set_repo_root_updates_artifacts(tmp_path):
    context = RepoContext(tmp_path)
    new_root = tmp_path / "other"
    new_root.mkdir()
    context.set_repo_root(new_root)
    assert context.get_repo_root() == new_root
    assert context.journal == new_root / ".agent" / "journal.jsonl"
    assert context.snapshot == new_root / ".agent" / "snapshot.json"
    assert context.checkpoint == new_root / ".agent" / "checkpoint.json"
    assert context.handoff == new_root / ".agent" / "handoff.json"
    assert context.observability == new_root / ".agent" / "observability_summary.json"
    assert context.tx_event_log == new_root / ".agent" / "tx_event_log.jsonl"
    assert context.tx_state == new_root / ".agent" / "tx_state.json"
