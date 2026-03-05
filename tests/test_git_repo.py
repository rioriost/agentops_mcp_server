import subprocess

import pytest

from agentops_mcp_server.git_repo import GitRepo


class DummyRepoContext:
    def __init__(self, root):
        self._root = root

    def get_repo_root(self):
        return self._root


def test_git_returns_output(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))

    def fake_check_output(args, cwd, stderr):
        assert cwd == str(tmp_path)
        return b"ok\n"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    assert repo.git("status") == "ok"


def test_git_handles_file_not_found(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))

    def boom(*_args, **_kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(subprocess, "check_output", boom)

    with pytest.raises(RuntimeError, match="git is not installed"):
        repo.git("status")


def test_git_handles_called_process_error(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))

    def boom(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git"], output=b"bad")

    monkeypatch.setattr(subprocess, "check_output", boom)

    with pytest.raises(RuntimeError, match="bad"):
        repo.git("status")


def test_status_porcelain_splits_lines(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))

    def fake_check_output(args, cwd, stderr):
        return b" M a\n?? b\n\n"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    assert repo.status_porcelain() == ["M a", "?? b"]


def test_diff_stat_calls_git(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))
    calls = []

    def fake_check_output(args, cwd, stderr):
        calls.append(args)
        return b"diff"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    assert repo.diff_stat() == "diff"
    assert calls[0] == ["git", "diff", "--stat"]


def test_diff_stat_cached_calls_git(monkeypatch, tmp_path):
    repo = GitRepo(DummyRepoContext(tmp_path))
    calls = []

    def fake_check_output(args, cwd, stderr):
        calls.append(args)
        return b"diff"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    assert repo.diff_stat_cached() == "diff"
    assert calls[0] == ["git", "diff", "--stat", "--cached"]
