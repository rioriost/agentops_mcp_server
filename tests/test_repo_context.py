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


def test_set_repo_root_updates_artifacts(tmp_path):
    context = RepoContext(tmp_path)
    new_root = tmp_path / "other"
    new_root.mkdir()
    context.set_repo_root(new_root)
    assert context.get_repo_root() == new_root
    assert context.journal == new_root / ".agent" / "journal.jsonl"
