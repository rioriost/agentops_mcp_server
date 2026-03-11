import json
from datetime import datetime, timezone

import pytest

from agentops_mcp_server.ops_tools import (
    OpsTools,
    build_compact_context,
    summarize_result,
    truncate_text,
)
from agentops_mcp_server.workflow_response import (
    canonical_idle_baseline,
    is_canonical_idle_baseline,
    is_valid_active_exact_resume_tx_state,
    is_valid_exact_resume_tx_state,
)


class DummyGitRepo:
    def __init__(self, diff_value="diff", diff_error=None):
        self.diff_value = diff_value
        self.diff_error = diff_error

    def diff_stat(self):
        if self.diff_error is not None:
            raise self.diff_error
        return self.diff_value


def _build_ops_tools(repo_context, state_store, state_rebuilder, git_repo=None):
    return OpsTools(
        repo_context,
        state_store,
        state_rebuilder,
        git_repo or DummyGitRepo(),
    )


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_events(repo_context):
    if not repo_context.tx_event_log.exists():
        return []
    return [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_types(repo_context):
    return [event["event_type"] for event in _read_events(repo_context)]


def _active_tx_state(
    *,
    tx_id=1,
    ticket_id="p1-t1",
    status="in-progress",
    phase=None,
    current_step="task",
    next_action="tx.verify.start",
    semantic_summary="Entered step task",
    session_id="s1",
    verify_state=None,
    commit_state=None,
):
    resolved_phase = phase or status
    verify = verify_state or {"status": "not_started", "last_result": None}
    commit = commit_state or {"status": "not_started", "last_result": None}
    return {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": resolved_phase,
            "current_step": current_step,
            "last_completed_step": "",
            "next_action": next_action,
            "semantic_summary": semantic_summary,
            "user_intent": None,
            "session_id": session_id,
            "verify_state": verify,
            "commit_state": commit,
            "file_intents": [],
        },
        "status": status,
        "next_action": next_action,
        "semantic_summary": semantic_summary,
        "verify_state": verify,
        "commit_state": commit,
        "last_applied_seq": 0,
        "integrity": {
            "state_hash": "test-hash",
            "rebuilt_from_seq": 0,
            "drift_detected": False,
            "active_tx_source": "materialized",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }


def _seed_active_tx(repo_context, **overrides):
    state = _active_tx_state(**overrides)
    _write_json(repo_context.tx_state, state)
    return state


def _seed_terminal_tx(repo_context, **overrides):
    state = _active_tx_state(**overrides)
    state["status"] = overrides.get("status", "done")
    state["next_action"] = overrides.get("next_action", "tx.begin")
    _write_json(repo_context.tx_state, state)
    return state


def _seed_idle_state(repo_context):
    _write_json(
        repo_context.tx_state,
        {
            "schema_version": "0.4.0",
            "active_tx": None,
            "status": None,
            "next_action": "tx.begin",
            "semantic_summary": None,
            "verify_state": None,
            "commit_state": None,
            "last_applied_seq": 0,
            "integrity": {
                "state_hash": "idle-hash",
                "rebuilt_from_seq": 0,
                "drift_detected": False,
                "active_tx_source": "none",
            },
            "updated_at": "2026-03-08T00:00:00+00:00",
        },
    )


def _begin_tx(
    state_store, state_rebuilder, tx_id=1, ticket_id="p1-t1", session_id="s1"
):
    state_store.repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    state_store.repo_context.tx_event_log.write_text("", encoding="utf-8")
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_event_append_and_state_save(
        tx_id=tx_id,
        ticket_id=ticket_id,
        event_type="tx.begin",
        phase="in-progress",
        step_id="none",
        actor={"tool": "test"},
        session_id=session_id,
        payload={"ticket_id": ticket_id, "ticket_title": ticket_id},
        state=rebuild["state"],
    )
    tx_state = json.loads(state_store.repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["status"] = "in-progress"
    tx_state["active_tx"]["phase"] = "in-progress"
    tx_state["active_tx"]["current_step"] = "task"
    tx_state["active_tx"]["next_action"] = "tx.verify.start"
    tx_state["active_tx"]["semantic_summary"] = f"Started transaction {ticket_id}"
    tx_state["active_tx"]["verify_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["status"] = "in-progress"
    tx_state["next_action"] = "tx.verify.start"
    tx_state["semantic_summary"] = f"Started transaction {ticket_id}"
    tx_state["verify_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    tx_state["commit_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    integrity = tx_state.get("integrity")
    if isinstance(integrity, dict):
        integrity["active_tx_source"] = "materialized"
    state_store.tx_state_save(tx_state)


def _assert_guidance_fields(result):
    assert result["ok"] is True
    assert "canonical_status" in result
    assert "canonical_phase" in result
    assert "next_action" in result
    assert "terminal" in result
    assert "requires_followup" in result
    assert "followup_tool" in result
    assert "active_tx_id" in result
    assert "active_ticket_id" in result
    assert "current_step" in result
    assert "verify_status" in result
    assert "commit_status" in result
    assert "integrity_status" in result


def test_truncate_text_handles_none_and_bounds():
    assert truncate_text(None) is None
    assert truncate_text("abc", limit=0) == ""
    assert truncate_text("abc", limit=10) == "abc"
    assert truncate_text("abcdef", limit=3) == "abc...(truncated)"


def test_load_tx_state_falls_back_to_rebuild_when_materialized_missing(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(
            {
                "seq": 1,
                "event_id": "evt-1",
                "ts": "2026-03-08T00:00:00+00:00",
                "project_root": "test-root",
                "tx_id": 1,
                "ticket_id": "p1-t1",
                "event_type": "tx.begin",
                "phase": "in-progress",
                "step_id": "none",
                "actor": {"tool": "test"},
                "session_id": "s1",
                "payload": {"ticket_id": "p1-t1", "ticket_title": "p1-t1"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._load_tx_state()

    assert result["active_tx"]["tx_id"] == 1
    assert result["active_tx"]["ticket_id"] == "p1-t1"


def test_load_tx_state_returns_canonical_idle_baseline_when_materialized_missing_and_rebuild_fails(
    repo_context, state_store
):
    ops = _build_ops_tools(
        repo_context,
        state_store,
        DummyStateRebuilder({"ok": False}),
    )

    result = ops._load_tx_state()

    assert result == canonical_idle_baseline()
    assert is_canonical_idle_baseline(result) is True
    assert is_valid_exact_resume_tx_state(result) is True


def test_shared_resume_helpers_accept_only_canonical_idle_baseline():
    baseline = canonical_idle_baseline()

    assert is_canonical_idle_baseline(baseline) is True
    assert is_valid_exact_resume_tx_state(baseline) is True

    noncanonical = {
        **baseline,
        "next_action": "tx.verify.start",
    }

    assert is_canonical_idle_baseline(noncanonical) is False
    assert is_valid_exact_resume_tx_state(noncanonical) is False


def test_shared_resume_helpers_validate_active_exact_resume_state():
    state = _active_tx_state()

    assert is_valid_active_exact_resume_tx_state(state) is True
    assert is_valid_exact_resume_tx_state(state) is True

    invalid_state = {
        **state,
        "next_action": "",
    }

    assert is_valid_active_exact_resume_tx_state(invalid_state) is False
    assert is_valid_exact_resume_tx_state(invalid_state) is False
        "verify_state": None,
        "commit_state": None,
        "semantic_summary": None,
        "integrity": {},
    }


def test_load_tx_state_prefers_materialized_idle_state_over_drifted_rebuild(
    repo_context, state_store, state_rebuilder
):
    _seed_idle_state(repo_context)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "first"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "duplicate"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._load_tx_state()

    assert result["active_tx"] is None
    assert result["status"] is None
    assert result["next_action"] == "tx.begin"


def test_load_tx_state_rejects_malformed_no_active_materialized_state(
    repo_context, state_store, state_rebuilder
):
    _write_json(
        repo_context.tx_state,
        {
            "schema_version": "0.4.0",
            "active_tx": None,
            "status": None,
            "next_action": "resume somehow",
            "semantic_summary": None,
            "verify_state": None,
            "commit_state": None,
            "last_applied_seq": 0,
            "integrity": {
                "state_hash": "idle-hash",
                "rebuilt_from_seq": 0,
                "drift_detected": False,
                "active_tx_source": "none",
            },
            "updated_at": "2026-03-08T00:00:00+00:00",
        },
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError) as exc_info:
        ops._load_tx_state()

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "invalid_ordering"
    assert (
        payload["reason"]
        == "resume blocked because rebuilt canonical state is incomplete"
    )


def test_load_tx_state_accepts_rebuilt_no_active_baseline_when_materialized_missing(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    if repo_context.tx_state.exists():
        repo_context.tx_state.unlink()
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._load_tx_state()

    assert result["active_tx"] is None
    assert result["status"] is None
    assert result["next_action"] == "tx.begin"
    assert result["verify_state"] is None
    assert result["commit_state"] is None


def test_materialized_active_tx_returns_empty_for_non_dict_state(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text("[]\n", encoding="utf-8")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._materialized_active_tx() == {}


def test_parse_iso_datetime_handles_invalid_inputs(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._parse_iso_datetime(None) is None
    assert ops._parse_iso_datetime("") is None
    assert ops._parse_iso_datetime("not-a-date") is None
    assert ops._parse_iso_datetime("2026-03-08T00:00:00Z") == datetime(
        2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc
    )


def test_build_compact_context_includes_only_present_fields():
    summary = build_compact_context(
        {
            "session_id": "s1",
            "current_phase": "checking",
            "current_task": "p1-t1",
            "last_action": "Ran verify",
            "next_step": "tx.commit.start",
            "verification_status": "passed",
            "last_commit": "",
            "last_error": "",
        },
        " file.py | 1 +\n 1 file changed, 1 insertion(+)",
        400,
    )

    assert "session_id: s1" in summary
    assert "current_phase: checking" in summary
    assert "current_task: p1-t1" in summary
    assert "last_action: Ran verify" in summary
    assert "next_step: tx.commit.start" in summary
    assert "verification_status: passed" in summary
    assert "diff_stat:" in summary
    assert "1 file changed" in summary
    assert "last_commit:" not in summary
    assert "last_error:" not in summary


def test_iter_candidate_session_ids_from_agent_artifact_reads_json(
    repo_context, state_store, state_rebuilder
):
    payload_path = repo_context.get_repo_root() / ".agent" / "extra.json"
    _write_json(
        payload_path,
        {
            "session_id": "s-top",
            "nested": {"session_id": "s-nested"},
            "items": [{"session_id": "s-list"}],
            "updated_at": "2026-03-08T00:00:00+00:00",
        },
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._iter_candidate_session_ids_from_agent_artifact(payload_path, None)

    assert result == ["s-top", "s-nested", "s-list"]


def test_iter_candidate_session_ids_from_agent_artifact_filters_json_by_debug_time(
    repo_context, state_store, state_rebuilder
):
    payload_path = repo_context.get_repo_root() / ".agent" / "extra.json"
    _write_json(
        payload_path,
        {
            "session_id": "s-top",
            "updated_at": "2026-03-07T23:59:59+00:00",
        },
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._iter_candidate_session_ids_from_agent_artifact(
        payload_path,
        datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result == []


def test_iter_candidate_session_ids_from_agent_artifact_reads_jsonl(
    repo_context, state_store, state_rebuilder
):
    payload_path = repo_context.get_repo_root() / ".agent" / "extra.jsonl"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        "\n".join(
            [
                json.dumps({"ts": "2026-03-08T00:00:00+00:00", "session_id": "s1"}),
                json.dumps(
                    {"ts": "2026-03-08T00:00:01+00:00", "nested": {"session_id": "s2"}}
                ),
                "{bad",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._iter_candidate_session_ids_from_agent_artifact(
        payload_path,
        datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert result == ["s1", "s2"]


def test_build_compact_context_falls_back_when_empty():
    assert build_compact_context({}, None, 200) == "no recent state available"


def test_debug_start_time_returns_none_without_file(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._debug_start_time() is None


def test_debug_start_time_reads_timestamp(repo_context, state_store, state_rebuilder):
    debug_path = repo_context.get_repo_root() / ".agent" / "debug_start_time.json"
    _write_json(debug_path, {"debug_start_time": "2026-03-08T00:00:00+00:00"})
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._debug_start_time()

    assert result == datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc)


def test_summarize_result_preserves_small_payloads():
    payload = {"ok": True, "value": "small"}
    assert summarize_result(payload, limit=200) == payload


def test_summarize_result_truncates_large_payloads():
    payload = {"value": "x" * 500}
    result = summarize_result(payload, limit=60)

    assert result["truncated"] is True
    assert result["summary"].endswith("...(truncated)")


def test_summarize_result_handles_non_json_serializable_value():
    result = summarize_result({"value": {1, 2, 3}}, limit=10)

    assert result["truncated"] is True
    assert result["summary"].endswith("...(truncated)")


def test_recover_session_id_from_agent_artifacts_uses_matching_tx_event(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=7, ticket_id="p7-t1", session_id="")
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 7,
                        "ticket_id": "p7-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "recovered-s1",
                        "payload": {"ticket_id": "p7-t1", "ticket_title": "p7-t1"},
                    }
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._recover_session_id_from_agent_artifacts(
        {"tx_id": 7, "ticket_id": "p7-t1"}
    )

    assert result == "recovered-s1"


def test_recover_session_id_from_agent_artifacts_uses_fallback_artifact(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=7, ticket_id="p7-t1", session_id="")
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    fallback = repo_context.get_repo_root() / ".agent" / "fallback.json"
    _write_json(
        fallback,
        {"session_id": "fallback-s1", "updated_at": "2026-03-08T00:00:00+00:00"},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._recover_session_id_from_agent_artifacts(
        {"tx_id": 7, "ticket_id": "p7-t1"}
    )

    assert result == "fallback-s1"


def test_recover_session_id_from_agent_artifacts_rejects_ambiguous_matches(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=7, ticket_id="p7-t1", session_id="")
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 7,
                        "ticket_id": "p7-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p7-t1", "ticket_title": "p7-t1"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": "test-root",
                        "tx_id": 7,
                        "ticket_id": "p7-t1",
                        "event_type": "tx.step.enter",
                        "phase": "in-progress",
                        "step_id": "task",
                        "actor": {"tool": "test"},
                        "session_id": "s2",
                        "payload": {"step_id": "task", "description": "task started"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="unable to recover a unique prior session_id"):
        ops._recover_session_id_from_agent_artifacts({"tx_id": 7, "ticket_id": "p7-t1"})


def test_resolve_session_id_prefers_explicit_value(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context, tx_id=7, ticket_id="p7-t1", session_id="materialized-s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._resolve_session_id(" explicit-s1 ", {"tx_id": 7}) == "explicit-s1"


def test_resolve_session_id_falls_back_to_materialized_value(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert (
        ops._resolve_session_id(
            None, {"session_id": "materialized-s1"}, allow_recovery=False
        )
        == "materialized-s1"
    )


def test_resolve_session_id_returns_empty_when_unrecoverable(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._resolve_session_id(None, {}, allow_recovery=False) == ""


def test_ops_compact_context_defaults_and_includes_diff(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        semantic_summary="Entered step resume-step",
    )
    git_repo = DummyGitRepo(
        diff_value=" file.py | 1 +\n 1 file changed, 1 insertion(+)"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder, git_repo)

    result = ops.ops_compact_context(max_chars=None, include_diff=True)

    assert result["ok"] is True
    assert result["max_chars"] == 800
    assert result["include_diff"] is True
    assert "current_phase: checking" in result["compact_context"]
    assert "current_task: p1-t1" in result["compact_context"]
    assert "last_action: Entered step resume-step" in result["compact_context"]
    assert "next_step: tx.verify.start" in result["compact_context"]
    assert "diff_stat:" in result["compact_context"]
    assert "1 file changed" in result["compact_context"]


def test_workflow_success_response_builds_idle_guidance_when_state_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._workflow_success_response(payload={"ok": True}, tx_state={})

    assert result["ok"] is True
    assert result["canonical_status"] == ""
    assert result["next_action"] == "tx.begin"
    assert result["can_start_new_ticket"] is True
    assert result["active_tx"] is None
    assert result["integrity_status"] == "healthy"


def test_canonical_begin_conflict_reports_drift(
    repo_context, state_store, state_rebuilder
):
    _seed_idle_state(repo_context)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "first"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "duplicate"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    error = ops._canonical_begin_conflict("p1-t1")

    assert isinstance(error, ValueError)
    assert "integrity drift" in str(error)


def test_canonical_begin_conflict_blocks_rebegin_same_active_tx(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=9, ticket_id="p9-t1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    error = ops._canonical_begin_conflict("9")

    assert isinstance(error, ValueError)
    assert "already-active non-terminal transaction" in str(error)


def test_canonical_begin_conflict_returns_none_for_terminal_materialized_tx(
    repo_context, state_store, state_rebuilder
):
    _seed_terminal_tx(repo_context, tx_id=9, ticket_id="p9-t1", status="done")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._canonical_begin_conflict("p9-t2") is None


def test_normalize_tx_identifier_handles_supported_values(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._normalize_tx_identifier(True) == ""
    assert ops._normalize_tx_identifier(12) == "12"
    assert ops._normalize_tx_identifier("  p1-t1 ") == "p1-t1"
    assert ops._normalize_tx_identifier(None) == ""


def test_ops_compact_context_truncates_without_diff(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        semantic_summary="x" * 200,
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=20, include_diff=False)

    assert result["ok"] is True
    assert result["max_chars"] == 20
    assert result["include_diff"] is False
    assert result["compact_context"].endswith("...(truncated)")


def test_active_tx_identity_and_terminal_detection(
    repo_context, state_store, state_rebuilder
):
    _seed_terminal_tx(repo_context, tx_id=11, ticket_id="p11-t1", status="blocked")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    active_tx = ops._active_tx()

    identity = ops._active_tx_identity(active_tx)

    assert identity["tx_id"] == "11"
    assert identity["ticket_id"] == "p11-t1"
    assert identity["canonical_id"] == "11"
    assert identity["has_canonical_tx"] is True
    assert ops._is_terminal_active_tx(active_tx) is True


def test_require_active_tx_without_identifier_returns_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=18, ticket_id="p18-t1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    active_tx, canonical_id = ops._require_active_tx()

    assert canonical_id == "18"
    assert active_tx["ticket_id"] == "p18-t1"


def test_require_active_tx_rejects_mismatched_identifier(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=19,
        ticket_id="p19-t1",
        status="checking",
        next_action="tx.commit.start",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="requested_task=p20-t1"):
        ops._require_active_tx("p20-t1")


def test_resolve_file_intent_context_defaults_task_id_to_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=61,
        ticket_id="p61-t1",
        current_step="p61-t1-s1",
        session_id="session-61",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    active_tx, active_tx_id, resolved_session_id = ops._resolve_file_intent_context(
        None, None
    )

    assert active_tx["ticket_id"] == "p61-t1"
    assert active_tx_id == "61"
    assert resolved_session_id == "session-61"


def test_require_active_tx_rejects_terminal_materialized_tx(
    repo_context, state_store, state_rebuilder
):
    _seed_terminal_tx(repo_context, tx_id=11, ticket_id="p11-t1", status="done")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops._require_active_tx("11")


def test_active_tx_mismatch_error_includes_context(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=14,
        ticket_id="p14-t1",
        status="checking",
        next_action="tx.commit.start",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    error = ops._active_tx_mismatch_error("p15-t1", ops._active_tx())

    assert "active_tx=14" in str(error)
    assert "requested_task=p15-t1" in str(error)
    assert "active_ticket=p14-t1" in str(error)
    assert "next_action=tx.commit.start" in str(error)


def test_ops_handoff_export_writes_json(repo_context, state_store, state_rebuilder):
    _seed_active_tx(
        repo_context,
        ticket_id="p1-t1",
        status="checking",
        phase="checking",
        semantic_summary="Entered step review",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["wrote"] is True
    payload = json.loads(repo_context.handoff.read_text(encoding="utf-8"))
    assert payload["current_task"] == "p1-t1"
    assert payload["last_action"] == "Entered step review"
    assert payload["next_step"] == "tx.verify.start"
    assert "compact_context" in payload


def test_ops_handoff_export_defaults_to_tx_begin_without_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["current_task"] == ""
    assert result["handoff"]["next_step"] == "tx.begin"


def test_ops_handoff_export_marks_integrity_blocked_when_rebuild_drifts(
    repo_context, state_store, state_rebuilder
):
    _seed_idle_state(repo_context)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "first"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p1-t1",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p1-t1", "ticket_title": "duplicate"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["integrity_status"] == "blocked"
    assert "blocked_reason" in result["handoff"]
    assert "recommended_action" in result["handoff"]


def test_ops_resume_brief_allows_new_ticket_when_idle(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=200)

    assert result["ok"] is True
    assert "resume_brief:" in result["brief"]
    assert "- can_start_new_ticket: yes" in result["brief"]


def test_ops_resume_brief_requires_resuming_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=5,
        ticket_id="p2-t3",
        status="checking",
        phase="checking",
        current_step="p2-t3",
        next_action="tx.commit.start",
        semantic_summary="Verification passed",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    assert "- active_ticket: p2-t3" in result["brief"]
    assert "- active_status: checking" in result["brief"]
    assert "- required_next_action: tx.commit.start" in result["brief"]
    assert "- can_start_new_ticket: no" in result["brief"]


def test_ops_start_task_requires_task_id_when_bootstrapping(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="task_id is required to bootstrap tx.begin"):
        ops.ops_start_task(title="Missing task id")


def test_ops_start_task_bootstraps_and_returns_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(
        RuntimeError,
        match="canonical event appended but tx_state synchronization failed",
    ):
        ops.ops_start_task(
            title="Implement workflow coverage",
            task_id="p3-t1",
            session_id="s1",
            agent_id="agent-test",
            status="in-progress",
        )

    assert _event_types(repo_context) == ["tx.begin", "tx.step.enter"]


def test_ops_start_task_reuses_exact_active_tx_identity_on_resume(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=17,
        ticket_id="p2-t01",
        status="in-progress",
        phase="in-progress",
        current_step="p2-t01",
        next_action="tx.verify.start",
        semantic_summary="Started transaction p2-t01",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    active_tx, canonical_id = ops._require_active_tx("17", allow_resume=True)

    assert canonical_id == "17"
    assert active_tx["tx_id"] == 17
    assert active_tx["ticket_id"] == "p2-t01"


def test_ops_start_task_accepts_ticket_id_when_resuming_current_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(
        state_store, state_rebuilder, tx_id=23, ticket_id="p2-t01", session_id="s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    active_tx, canonical_id = ops._require_active_tx("p2-t01", allow_resume=True)

    assert canonical_id == "23"
    assert active_tx["tx_id"] == 23
    assert active_tx["ticket_id"] == "p2-t01"


def test_ops_update_task_rejects_terminal_statuses(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(state_store, state_rebuilder, tx_id=1, ticket_id="p4-t1", session_id="s1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="use ops_end_task for terminal done state"):
        ops.ops_update_task(status="done", task_id="p4-t1", session_id="s1")

    with pytest.raises(ValueError, match="use ops_end_task for terminal blocked state"):
        ops.ops_update_task(status="blocked", task_id="p4-t1", session_id="s1")


def test_ops_update_task_updates_phase_and_records_user_intent(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(state_store, state_rebuilder, tx_id=9, ticket_id="p4-t2", session_id="s1")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_update_task(
        status="checking",
        note="Compare acceptance criteria",
        task_id="p4-t2",
        session_id="s1",
        user_intent="resume p4-t2",
    )

    _assert_guidance_fields(result)
    assert result["active_ticket_id"] == "p4-t2"
    assert _event_types(repo_context) == [
        "tx.begin",
        "tx.step.enter",
        "tx.user_intent.set",
    ]

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["phase"] == "checking"
    assert tx_state["active_tx"]["user_intent"] == "resume p4-t2"


def test_ops_end_task_requires_commit_before_done(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=11,
        ticket_id="p5-t1",
        status="verified",
        phase="verified",
        current_step="p5-t1",
        next_action="tx.commit.start",
        semantic_summary="Ready to commit",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(
        ValueError,
        match="cannot mark task done before commit is finished",
    ):
        ops.ops_end_task(
            summary="Verified but not committed",
            status="done",
            task_id="p5-t1",
            session_id="s1",
        )


def test_ops_end_task_closes_committed_task(repo_context, state_store, state_rebuilder):
    _seed_active_tx(
        repo_context,
        tx_id=12,
        ticket_id="p5-t2",
        status="committed",
        phase="committed",
        current_step="p5-t2",
        next_action="tx.end.done",
        semantic_summary="Committed changes",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={
            "status": "passed",
            "last_result": {"sha": "abc123", "summary": "done"},
        },
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_end_task(
        summary="All work completed",
        next_action="tx.begin",
        status="done",
        task_id="p5-t2",
        session_id="s1",
    )

    _assert_guidance_fields(result)
    assert result["terminal"] is False
    assert result["active_tx_id"] is None
    assert result["active_ticket_id"] is None
    assert result["next_action"] == "tx.begin"
    assert _event_types(repo_context)[-1] == "tx.end.done"


def test_ops_end_task_accepts_blocked_status(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=13,
        ticket_id="p5-t3",
        status="checking",
        phase="checking",
        current_step="p5-t3",
        next_action="tx.verify.start",
        semantic_summary="Verification pending",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_end_task(
        summary="Blocked by external dependency",
        status="blocked",
        task_id="p5-t3",
        session_id="s1",
    )

    _assert_guidance_fields(result)
    assert result["next_action"] == "tx.begin"
    assert result["active_tx_id"] is None
    assert _event_types(repo_context)[-1] == "tx.end.blocked"


def test_ops_end_task_rejects_invalid_terminal_status(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=14,
        ticket_id="p5-t4",
        status="committed",
        phase="committed",
        current_step="p5-t4",
        next_action="tx.end.done",
        semantic_summary="Ready to close",
        commit_state={"status": "passed", "last_result": {"sha": "abc"}},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="ops_end_task status must be done or blocked"):
        ops.ops_end_task(
            summary="invalid",
            status="checking",
            task_id="p5-t4",
            session_id="s1",
        )


def test_ops_capture_state_persists_rebuilt_state(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(
        state_store, state_rebuilder, tx_id=21, ticket_id="p6-t1", session_id="s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    assert result["last_applied_seq"] >= 1
    saved = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved["active_tx"]["ticket_id"] == "p6-t1"


def test_ops_capture_state_returns_blocked_failure_on_drift(
    repo_context, state_store, state_rebuilder
):
    _seed_idle_state(repo_context)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p6-t2",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p6-t2", "ticket_title": "first"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": "test-root",
                        "tx_id": 1,
                        "ticket_id": "p6-t2",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p6-t2", "ticket_title": "duplicate"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["error_code"] == "integrity_drift_detected"
    assert result["blocked"] is True
    assert result["recommended_next_tool"] == "tx_state_rebuild"


def test_ops_task_summary_reflects_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=31,
        ticket_id="p7-t1",
        status="checking",
        phase="checking",
        current_step="p7-t1",
        next_action="tx.commit.start",
        semantic_summary="Compared acceptance criteria",
        verify_state={"status": "passed", "last_result": {"ok": True}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=400)

    assert result["ok"] is True
    assert result["summary"]["task_id"] == "p7-t1"
    assert result["summary"]["task_status"] == "checking"
    assert result["summary"]["next_step"] == "tx.commit.start"
    assert "task_summary:" in result["text"]


def test_ops_task_summary_uses_failure_reason_from_verify_or_commit(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=32,
        ticket_id="p7-t2",
        status="checking",
        phase="checking",
        current_step="p7-t2",
        next_action="tx.verify.start",
        semantic_summary="Verification failed",
        verify_state={"status": "failed", "last_result": {"error": "verify boom"}},
        commit_state={"status": "not_started", "last_result": None},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=400)

    assert result["ok"] is True
    assert result["summary"]["failure_reason"] == "verify boom"
    assert "failure_reason: verify boom" in result["text"]


def test_ops_observability_summary_writes_json_and_text(
    repo_context, state_store, state_rebuilder
):
    _begin_tx(
        state_store, state_rebuilder, tx_id=41, ticket_id="p8-t1", session_id="s1"
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(
        session_id="s1",
        max_events=10,
        max_chars=300,
    )

    assert result["ok"] is True
    assert result["max_events"] == 10
    assert result["max_chars"] == 300
    assert repo_context.observability.exists()
    payload = json.loads(repo_context.observability.read_text(encoding="utf-8"))
    assert payload["session_id"] == "s1"
    assert isinstance(payload["recent_events"], list)


def test_ops_observability_summary_includes_failure_reason_text(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=42,
        ticket_id="p8-t2",
        status="checking",
        phase="checking",
        current_step="p8-t2",
        next_action="tx.verify.start",
        semantic_summary="Verification failed",
        verify_state={"status": "failed", "last_result": {"error": "bad verify"}},
        commit_state={"status": "not_started", "last_result": None},
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(
            {
                "seq": 1,
                "event_id": "evt-1",
                "ts": "2026-03-08T00:00:00+00:00",
                "project_root": "test-root",
                "tx_id": 42,
                "ticket_id": "p8-t2",
                "event_type": "tx.verify.fail",
                "phase": "checking",
                "step_id": "p8-t2",
                "actor": {"tool": "test"},
                "session_id": "s1",
                "payload": {"ok": False, "error": "bad verify"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(
        session_id="s1",
        max_events=5,
        max_chars=300,
    )

    assert result["ok"] is True
    assert "failure_reason: bad verify" in result["text"]
    assert result["summary"]["failure_reason"] == "bad verify"


def test_ops_resume_brief_reports_integrity_drift(
    repo_context, state_store, state_rebuilder
):
    _seed_idle_state(repo_context)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "event_id": "evt-1",
                        "ts": "2026-03-08T00:00:00+00:00",
                        "project_root": str(repo_context.get_repo_root()),
                        "tx_id": 1,
                        "ticket_id": "p2-t3",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p2-t3", "ticket_title": "first"},
                    }
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "event_id": "evt-2",
                        "ts": "2026-03-08T00:00:01+00:00",
                        "project_root": str(repo_context.get_repo_root()),
                        "tx_id": 1,
                        "ticket_id": "p2-t3",
                        "event_type": "tx.begin",
                        "phase": "in-progress",
                        "step_id": "none",
                        "actor": {"tool": "test"},
                        "session_id": "s1",
                        "payload": {"ticket_id": "p2-t3", "ticket_title": "duplicate"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    assert "- status: blocked" in result["brief"]
    assert "- blocked_reason: duplicate tx.begin" in result["brief"]


def test_ops_add_update_and_complete_file_intent(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=50,
        ticket_id="p9-t1",
        status="in-progress",
        phase="in-progress",
        current_step="p9-t1-s1",
        next_action="tx.verify.start",
        semantic_summary="Started transaction p9-t1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    add_result = ops.ops_add_file_intent(
        path="tests/test_example.py",
        operation="update",
        purpose="align tests",
        task_id="p9-t1",
        session_id="s1",
    )
    _assert_guidance_fields(add_result)

    update_result = ops.ops_update_file_intent(
        path="tests/test_example.py",
        state="started",
        task_id="p9-t1",
        session_id="s1",
    )
    _assert_guidance_fields(update_result)

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["verify_state"] = {"status": "passed", "last_result": {"ok": True}}
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    _write_json(repo_context.tx_state, tx_state)

    update_verified = ops.ops_update_file_intent(
        path="tests/test_example.py",
        state="verified",
        task_id="p9-t1",
        session_id="s1",
    )
    _assert_guidance_fields(update_verified)

    complete_result = ops.ops_complete_file_intent(
        path="tests/test_example.py",
        task_id="p9-t1",
        session_id="s1",
    )
    _assert_guidance_fields(complete_result)

    assert _event_types(repo_context) == [
        "tx.file_intent.add",
        "tx.file_intent.update",
        "tx.file_intent.update",
        "tx.file_intent.complete",
    ]


def test_ops_add_file_intent_requires_current_step(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=51,
        ticket_id="p9-t2",
        current_step="",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(
        ValueError, match="current_step is required before adding file intent"
    ):
        ops.ops_add_file_intent(
            path="tests/test_example.py",
            operation="update",
            purpose="align tests",
            task_id="p9-t2",
            session_id="s1",
        )


def test_ops_add_file_intent_requires_path_operation_and_purpose(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=52,
        ticket_id="p9-t3",
        current_step="p9-t3-s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_add_file_intent(
            path="",
            operation="update",
            purpose="align tests",
            task_id="p9-t3",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="operation is required"):
        ops.ops_add_file_intent(
            path="tests/test_example.py",
            operation="",
            purpose="align tests",
            task_id="p9-t3",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="purpose is required"):
        ops.ops_add_file_intent(
            path="tests/test_example.py",
            operation="update",
            purpose="",
            task_id="p9-t3",
            session_id="s1",
        )


def test_ops_update_file_intent_requires_path_and_state(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=53,
        ticket_id="p9-t4",
        current_step="p9-t4-s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_update_file_intent(
            path="",
            state="started",
            task_id="p9-t4",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="state is required"):
        ops.ops_update_file_intent(
            path="tests/test_example.py",
            state="",
            task_id="p9-t4",
            session_id="s1",
        )


def test_ops_complete_file_intent_requires_path(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(
        repo_context,
        tx_id=54,
        ticket_id="p9-t5",
        current_step="p9-t5-s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_complete_file_intent(
            path="",
            task_id="p9-t5",
            session_id="s1",
        )


def test_ops_update_task_without_status_or_note_uses_task_id_payload(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=55, ticket_id="p9-t6")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_update_task(task_id="p9-t6", session_id="s1")

    _assert_guidance_fields(result)
    assert result["active_ticket_id"] == "p9-t6"


def test_ops_update_task_rejects_unsupported_status(
    repo_context, state_store, state_rebuilder
):
    _seed_active_tx(repo_context, tx_id=56, ticket_id="p9-t7")
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="unsupported status for ops_update_task"):
        ops.ops_update_task(status="paused", task_id="p9-t7", session_id="s1")


def test_ops_end_task_requires_summary(repo_context, state_store, state_rebuilder):
    _seed_active_tx(
        repo_context,
        tx_id=57,
        ticket_id="p9-t8",
        status="committed",
        phase="committed",
        commit_state={"status": "passed", "last_result": {"sha": "abc"}},
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="summary is required"):
        ops.ops_end_task(
            summary="",
            status="done",
            task_id="p9-t8",
            session_id="s1",
        )
