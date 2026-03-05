from agentops_mcp_server import main as m


def test_normalize_commit_message_truncates_and_cleans():
    assert m._normalize_commit_message("  hello\nworld  ") == "hello world"
    long = "x" * 200
    normalized = m._normalize_commit_message(long)
    assert normalized.endswith("...")
    assert len(normalized) <= 80


def test_post_commit_snapshot_checkpoint_logs_skip(monkeypatch):
    calls = []

    monkeypatch.setattr(
        m,
        "_auto_snapshot_checkpoint_after_commit",
        lambda: {"ok": False, "reason": "nope"},
    )
    monkeypatch.setattr(
        m, "_journal_safe", lambda kind, payload: calls.append((kind, payload))
    )

    m._post_commit_snapshot_checkpoint()

    assert calls
    kind, payload = calls[0]
    assert kind == "error"
    assert payload["message"] == "auto snapshot/checkpoint skipped"


def test_post_commit_snapshot_checkpoint_logs_failure(monkeypatch):
    calls = []

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(m, "_auto_snapshot_checkpoint_after_commit", boom)
    monkeypatch.setattr(
        m, "_journal_safe", lambda kind, payload: calls.append((kind, payload))
    )

    m._post_commit_snapshot_checkpoint()

    assert calls
    kind, payload = calls[0]
    assert kind == "error"
    assert payload["message"] == "auto snapshot/checkpoint failed"


def test_run_git_commit_records_commit_end_and_post(monkeypatch):
    monkeypatch.setattr(m, "_git_diff_stat_cached", lambda: "diff")
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kwargs: None)

    def fake_git(*args):
        if args == ("rev-parse", "HEAD"):
            return "abc"
        return ""

    monkeypatch.setattr(m, "git", fake_git)

    calls = []
    monkeypatch.setattr(
        m, "_journal_safe", lambda kind, payload: calls.append((kind, payload))
    )

    post = {"called": False}
    monkeypatch.setattr(
        m, "_post_commit_snapshot_checkpoint", lambda: post.__setitem__("called", True)
    )

    sha, summary = m._run_git_commit("msg")

    assert (sha, summary) == ("abc", "diff")
    assert post["called"] is True

    commit_events = [payload for kind, payload in calls if kind == "commit.end"]
    assert commit_events
    assert commit_events[0]["ok"] is True
    assert commit_events[0]["sha"] == "abc"
