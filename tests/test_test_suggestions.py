import pytest

from agentops_mcp_server.repo_context import RepoContext
from agentops_mcp_server.test_suggestions import (
    TestSuggester,
    candidates_for_path,
    extract_artifact_paths,
    is_test_path,
    normalize_test_candidate,
    parse_changed_files,
    unique_preserve_order,
)


class DummyGitRepo:
    def git(self, *args):
        return ""


class DummyGitRepoWithDiffs:
    def __init__(self, unstaged="", staged=""):
        self.unstaged = unstaged
        self.staged = staged

    def git(self, *args):
        if args == ("diff", "--name-only"):
            return self.unstaged
        if args == ("diff", "--name-only", "--cached"):
            return self.staged
        return ""


def test_unique_preserve_order():
    assert unique_preserve_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_extract_artifact_paths_dedupes():
    events = [
        {"payload": {"path": "a.txt", "files": ["b.txt", "a.txt"]}},
        {"payload": {"file": "c.txt", "paths": ["d.txt", "b.txt"]}},
        {"payload": {"path": "  ", "files": [None, ""]}},
    ]
    assert extract_artifact_paths(events) == ["a.txt", "b.txt", "c.txt", "d.txt"]


def test_extract_artifact_paths_ignores_non_dict_payloads():
    events = [
        {"payload": None},
        {"payload": "not-a-dict"},
        {"payload": {"paths": ["x.py", " ", None], "file": "y.py"}},
    ]
    assert extract_artifact_paths(events) == ["y.py", "x.py"]


def test_is_test_path():
    assert is_test_path("tests/test_sample.py") is True
    assert is_test_path("src/tests/sample.py") is True
    assert is_test_path("test/sample.py") is True
    assert is_test_path("__tests__/sample.py") is True
    assert is_test_path("src/agentops_mcp_server/main.py") is False


def test_normalize_test_candidate_respects_existing_test_name():
    assert normalize_test_candidate("tests/test_main.py", ".py") == "tests/test_main.py"
    assert normalize_test_candidate("tests/main.py", ".py") == "tests/main_test.py"


def test_normalize_test_candidate_without_suffix_returns_original():
    assert normalize_test_candidate("tests/main", "") == "tests/main"


def test_candidates_for_path_generates_variants():
    candidates = candidates_for_path("src/agentops_mcp_server/main.py")
    assert "src/agentops_mcp_server/main_test.py" in candidates
    assert "src/agentops_mcp_server/test_main.py" in candidates
    assert "tests/agentops_mcp_server/main_test.py" in candidates


def test_candidates_for_path_handles_multi_suffix_and_library_paths():
    candidates = candidates_for_path("pkg/module/component.test.tsx")
    assert "pkg/module/component_test.test.tsx" in candidates
    assert "pkg/module/test_component.test.tsx" in candidates

    lib_candidates = candidates_for_path("src/lib/service.ts")
    assert "src/tests/service_test.ts" in lib_candidates
    assert "src/test/service_test.ts" in lib_candidates


def test_candidates_for_path_returns_existing_test_path_unchanged():
    assert candidates_for_path("tests/unit/sample_test.py") == [
        "tests/unit/sample_test.py"
    ]


def test_candidates_for_path_non_code_returns_empty():
    assert candidates_for_path("README.md") == []


def test_parse_changed_files_from_diff_blocks():
    diff = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "diff --git a/docs/readme.md b/docs/readme.md\n"
    )
    assert parse_changed_files(diff) == ["src/foo.py", "docs/readme.md"]


def test_parse_changed_files_from_name_list():
    diff = "alpha.txt\nbeta/gamma.md\n"
    assert parse_changed_files(diff) == ["alpha.txt", "beta/gamma.md"]


def test_parse_changed_files_strips_a_prefix_in_diff_blocks():
    diff = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "diff --git a/tests/test_bar.py b/tests/test_bar.py\n"
    )
    assert parse_changed_files(diff) == ["src/foo.py", "tests/test_bar.py"]


def test_tests_suggest_for_src_path(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    diff = "src/agentops_mcp_server/main.py\n"
    result = suggester.tests_suggest(diff=diff)
    paths = {item["path"] for item in result["suggestions"]}

    assert "tests/agentops_mcp_server/main_test.py" in paths


def test_tests_suggest_uses_git_diff_when_diff_not_provided(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(
        DummyGitRepoWithDiffs(
            unstaged="src/agentops_mcp_server/main.py\n",
            staged="tests/test_main.py\n",
        ),
        repo_context,
    )

    result = suggester.tests_suggest()
    suggestions = result["suggestions"]

    assert {
        "path": "tests/agentops_mcp_server/main_test.py",
        "reason": "covers src/agentops_mcp_server/main.py",
    } in suggestions
    assert {
        "path": "tests/test_main.py",
        "reason": "existing test changed",
    } in suggestions


def test_tests_suggest_for_test_path(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    diff = "tests/test_main.py\n"
    result = suggester.tests_suggest(diff=diff)

    assert result["suggestions"] == [
        {"path": "tests/test_main.py", "reason": "existing test changed"}
    ]


def test_tests_suggest_adds_investigate_once_and_handles_no_targets(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    result = suggester.tests_suggest(diff="README.md\n", failures="FAILED something\n")

    assert result["suggestions"] == [
        {"path": "(investigate)", "reason": "verify failures present"}
    ]


def test_tests_suggest_dedupes_candidates_across_src_and_changed_test_paths(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    result = suggester.tests_suggest(
        diff="src/agentops_mcp_server/main.py\ntests/agentops_mcp_server/main_test.py\n"
    )

    assert (
        result["suggestions"].count(
            {
                "path": "tests/agentops_mcp_server/main_test.py",
                "reason": "covers src/agentops_mcp_server/main.py",
            }
        )
        == 1
    )
    assert {
        "path": "tests/agentops_mcp_server/main_test.py",
        "reason": "existing test changed",
    } not in result["suggestions"]


def test_tests_suggest_keeps_single_investigate_entry_when_failures_and_test_paths_overlap(
    tmp_path,
):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    result = suggester.tests_suggest(
        diff="tests/test_main.py\n",
        failures="FAILED tests/test_main.py::test_case\n",
    )

    assert result["suggestions"] == [
        {"path": "tests/test_main.py", "reason": "existing test changed"},
        {"path": "(investigate)", "reason": "verify failures present"},
    ]


def test_tests_suggest_returns_none_when_no_targets_or_failures(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    result = suggester.tests_suggest(diff="README.md\n")

    assert result["suggestions"] == [
        {"path": "(none)", "reason": "no obvious test targets"}
    ]


def test_tests_suggest_from_failures_reads_log(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    log_path = tmp_path / "failures.log"
    log_path.write_text("FAILED test\n", encoding="utf-8")

    result = suggester.tests_suggest_from_failures("failures.log")

    assert result["suggestions"][0]["path"] == "(investigate)"


def test_tests_suggest_from_failures_accepts_absolute_log_path(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    log_path = tmp_path / "absolute-failures.log"
    log_path.write_text("FAILED absolute\n", encoding="utf-8")

    result = suggester.tests_suggest_from_failures(str(log_path))

    assert result["suggestions"] == [
        {"path": "(investigate)", "reason": "verify failures present"}
    ]


def test_tests_suggest_from_failures_requires_log_path(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    with pytest.raises(ValueError, match="log_path is required"):
        suggester.tests_suggest_from_failures("")


def test_tests_suggest_from_failures_missing_log(tmp_path):
    repo_context = RepoContext(tmp_path)
    suggester = TestSuggester(DummyGitRepo(), repo_context)

    with pytest.raises(FileNotFoundError):
        suggester.tests_suggest_from_failures("missing.log")
