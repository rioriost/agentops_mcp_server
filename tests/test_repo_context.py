from pathlib import Path

import pytest

from agentops_mcp_server.repo_context import RepoContext


def test_repo_context_starts_unresolved_when_root_is_slash():
    context = RepoContext(Path("/"))

    assert context.has_repo_root() is False
    assert context.repo_root is None
    assert context.tx_state is None
    assert context.tx_event_log is None
    assert context.handoff is None
    assert context.observability is None
    assert context.errors is None
    assert context.verify is None


def test_repo_context_starts_resolved_for_non_root_path(tmp_path):
    context = RepoContext(tmp_path)

    assert context.has_repo_root() is True
    assert context.get_repo_root() == tmp_path.resolve()
    assert context.tx_state == tmp_path / ".agent" / "tx_state.json"
    assert context.tx_event_log == tmp_path / ".agent" / "tx_event_log.jsonl"
    assert context.handoff == tmp_path / ".agent" / "handoff.json"
    assert context.observability == tmp_path / ".agent" / "observability_summary.json"
    assert context.errors == tmp_path / ".agent" / "errors.jsonl"
    assert context.verify == tmp_path / ".zed" / "scripts" / "verify"


def test_state_artifact_path_invalid_kind(repo_context):
    with pytest.raises(ValueError, match="unknown state artifact"):
        repo_context.state_artifact_path("nope")


def test_legacy_artifact_path_invalid_kind(repo_context):
    with pytest.raises(ValueError, match="unknown legacy artifact"):
        repo_context.legacy_artifact_path("nope")


def test_state_artifact_path_known_kind(repo_context):
    path = repo_context.state_artifact_path("tx_state")
    assert path.name == "tx_state.json"
    assert path.parent.name == ".agent"


def test_state_artifact_path_supports_errors_artifact(repo_context):
    path = repo_context.state_artifact_path("errors")
    assert path.name == "errors.jsonl"
    assert path.parent.name == ".agent"


def test_require_repo_root_fails_when_uninitialized():
    context = RepoContext(Path("/"))

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        context.require_repo_root()


def test_get_repo_root_fails_when_uninitialized():
    context = RepoContext(Path("/"))

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        context.get_repo_root()


def test_state_artifact_path_fails_when_uninitialized():
    context = RepoContext(Path("/"))

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        context.state_artifact_path("tx_state")


def test_legacy_artifact_path_fails_when_uninitialized():
    context = RepoContext(Path("/"))

    with pytest.raises(
        ValueError,
        match="project root is not initialized; call workspace_initialize\\(cwd\\)",
    ):
        context.legacy_artifact_path("journal")


def test_bind_repo_root_initializes_unresolved_context(tmp_path):
    context = RepoContext(Path("/"))

    result = context.bind_repo_root(tmp_path)

    assert result == {
        "ok": True,
        "repo_root": str(tmp_path.resolve()),
        "initialized": True,
        "changed": True,
    }
    assert context.has_repo_root() is True
    assert context.get_repo_root() == tmp_path.resolve()
    assert context.journal == tmp_path / ".agent" / "journal.jsonl"
    assert context.handoff == tmp_path / ".agent" / "handoff.json"
    assert context.observability == tmp_path / ".agent" / "observability_summary.json"
    assert context.tx_event_log == tmp_path / ".agent" / "tx_event_log.jsonl"
    assert context.tx_state == tmp_path / ".agent" / "tx_state.json"
    assert context.errors == tmp_path / ".agent" / "errors.jsonl"
    assert context.verify == tmp_path / ".zed" / "scripts" / "verify"


def test_bind_repo_root_same_path_is_noop(tmp_path):
    context = RepoContext(tmp_path)

    result = context.bind_repo_root(tmp_path)

    assert result == {
        "ok": True,
        "repo_root": str(tmp_path.resolve()),
        "initialized": True,
        "changed": False,
    }
    assert context.get_repo_root() == tmp_path.resolve()


def test_bind_repo_root_rejects_different_root(tmp_path):
    context = RepoContext(tmp_path)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError, match="repo_root is already initialized"):
        context.bind_repo_root(other)


def test_bind_repo_root_rejects_root_path():
    context = RepoContext(Path("/"))

    with pytest.raises(ValueError, match="repo_root cannot be '/'"):
        context.bind_repo_root(Path("/"))


def test_set_repo_root_updates_artifacts_from_unresolved(tmp_path):
    context = RepoContext(Path("/"))

    context.set_repo_root(tmp_path)

    assert context.get_repo_root() == tmp_path.resolve()
    assert context.journal == tmp_path / ".agent" / "journal.jsonl"
    assert context.handoff == tmp_path / ".agent" / "handoff.json"
    assert context.observability == tmp_path / ".agent" / "observability_summary.json"
    assert context.tx_event_log == tmp_path / ".agent" / "tx_event_log.jsonl"
    assert context.tx_state == tmp_path / ".agent" / "tx_state.json"
    assert context.errors == tmp_path / ".agent" / "errors.jsonl"
    assert context.verify == tmp_path / ".zed" / "scripts" / "verify"
