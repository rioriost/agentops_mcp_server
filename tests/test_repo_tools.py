import pytest

from agentops_mcp_server.repo_tools import RepoTools


class DummyGitRepo:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.calls = []

    def git(self, *args):
        self.calls.append(args)
        return self.mapping.get(args, "")

    def diff_stat(self):
        return self.mapping.get(("diff_stat",), "diff")

    def diff_stat_cached(self):
        return self.mapping.get(("diff_stat_cached",), "")


class DummyVerifyRunner:
    def __init__(self, result=None):
        self.result = result or {"ok": True}
        self.calls = []

    def run_verify(self, timeout_sec=None):
        self.calls.append(timeout_sec)
        return self.result


def test_repo_status_summary_collects_fields():
    mapping = {
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--short"): " M file.txt",
        ("log", "-1", "--oneline"): "abc123 msg",
        ("diff", "--name-only"): "file.txt",
        ("diff", "--name-only", "--cached"): "",
        ("diff_stat",): "diff",
        ("diff_stat_cached",): "cached",
    }
    git_repo = DummyGitRepo(mapping)
    verify_runner = DummyVerifyRunner()
    tools = RepoTools(git_repo, verify_runner)

    summary = tools.repo_status_summary()

    assert summary["branch"] == "main"
    assert summary["status"] == " M file.txt"
    assert summary["diff"] == "diff"
    assert summary["staged_diff"] == "cached"
    assert summary["last_commit"] == "abc123 msg"
    assert summary["files"]["unstaged"] == "file.txt"
    assert summary["files"]["staged"] == ""


@pytest.mark.parametrize(
    ("diff", "prefix"),
    [
        ("docs/readme.md\n", "docs"),
        ("tests/notes.md\n", "test"),
        ("src/agentops_mcp_server/main.py\n", "feat"),
        ("pyproject.toml\n", "chore"),
    ],
)
def test_repo_commit_message_suggest_prefix(diff, prefix):
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner()
    tools = RepoTools(git_repo, verify_runner)

    result = tools.repo_commit_message_suggest(diff=diff)

    assert result["files"]
    assert result["suggestions"][0].startswith(f"{prefix}:")


def test_repo_verify_delegates():
    git_repo = DummyGitRepo()
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tools = RepoTools(git_repo, verify_runner)

    result = tools.repo_verify(timeout_sec=5)

    assert result["ok"] is True
    assert verify_runner.calls == [5]


def test_session_capture_context_with_verify():
    git_repo = DummyGitRepo(
        {
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
            ("status", "--short"): "",
            ("log", "-1", "--oneline"): "abc msg",
            ("diff", "--name-only"): "",
            ("diff", "--name-only", "--cached"): "",
            ("diff_stat",): "",
            ("diff_stat_cached",): "",
        }
    )
    verify_runner = DummyVerifyRunner(result={"ok": True})
    tools = RepoTools(git_repo, verify_runner)

    context = tools.session_capture_context(run_verify=True)

    assert context["branch"] == "main"
    assert context["verify"]["ok"] is True
