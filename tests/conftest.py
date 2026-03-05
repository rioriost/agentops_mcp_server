import pytest

from agentops_mcp_server.repo_context import RepoContext
from agentops_mcp_server.state_rebuilder import StateRebuilder
from agentops_mcp_server.state_store import StateStore


@pytest.fixture
def repo_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return RepoContext(tmp_path)


@pytest.fixture
def state_store(repo_context):
    return StateStore(repo_context)


@pytest.fixture
def state_rebuilder(repo_context, state_store):
    return StateRebuilder(repo_context, state_store)
