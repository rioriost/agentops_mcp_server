import json

from agentops_mcp_server.ops_tools import OpsTools


class DummyGitRepo:
    def diff_stat(self) -> str:
        return "diff"


def _build_ops_tools(repo_context, state_store, state_rebuilder):
    return OpsTools(repo_context, state_store, state_rebuilder, DummyGitRepo())


def _journal_kinds(repo_context):
    return [
        json.loads(line)["kind"]
        for line in repo_context.journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_ops_compact_context_updates_snapshot_and_journal(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_compact_context(max_chars=80, include_diff=False)

    assert result["ok"] is True
    assert isinstance(result["compact_context"], str)

    loaded = state_store.snapshot_load()
    assert loaded["ok"] is True
    snapshot_state = loaded["snapshot"]["state"]
    assert snapshot_state["compact_context"] == result["compact_context"]

    kinds = _journal_kinds(repo_context)
    assert "context.compact" in kinds


def test_ops_handoff_export_writes_json(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["wrote"] is True
    assert result["path"]

    handoff_payload = json.loads(repo_context.handoff.read_text(encoding="utf-8"))
    assert "compact_context" in handoff_payload

    kinds = _journal_kinds(repo_context)
    assert "session.handoff" in kinds


def test_ops_task_summary_emits_journal(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    state_store.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )
    state_store.journal_append(
        kind="task.start",
        payload={"title": "Build", "task_id": "t-1"},
        session_id="s1",
        event_id="evt-1",
    )
    state_store.checkpoint_update(
        last_applied_seq=0, snapshot_path=repo_context.snapshot.name
    )

    result = ops.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_title"] == "Build"
    assert len(result["text"]) <= 40

    kinds = _journal_kinds(repo_context)
    assert "task.summary" in kinds


def test_ops_observability_summary_includes_artifacts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    state_store.snapshot_save(
        state={"current_phase": "session"}, session_id="s1", last_applied_seq=0
    )
    state_store.journal_append(
        kind="task.blocked",
        payload={"reason": "network down", "note": "blocked"},
        session_id="s1",
        event_id="evt-1",
    )
    state_store.journal_append(
        kind="file.edit",
        payload={"action": "edit", "path": "src/app.py"},
        session_id="s1",
        event_id="evt-2",
    )
    state_store.journal_append(
        kind="artifact.summary",
        payload={"paths": ["out/log.txt"]},
        session_id="s1",
        event_id="evt-3",
    )
    state_store.checkpoint_update(
        last_applied_seq=0, snapshot_path=repo_context.snapshot.name
    )

    result = ops.ops_observability_summary(session_id="s1", max_events=5, max_chars=200)
    assert result["ok"] is True
    summary = result["summary"]
    assert summary["failure_reason"] == "network down"
    assert "src/app.py" in summary["artifacts"]
    assert "out/log.txt" in summary["artifacts"]

    assert repo_context.observability.exists()
    text_path = repo_context.observability.with_suffix(".txt")
    assert text_path.exists()

    kinds = _journal_kinds(repo_context)
    assert "observability.summary" in kinds
