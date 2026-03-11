import json
from datetime import datetime, timezone

from agentops_mcp_server.state_rebuilder import StateRebuilder


def _append_raw_tx_event(repo_context, event):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    with repo_context.tx_event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _legacy_event(
    *,
    seq,
    kind,
    session_id="legacy-s1",
    event_id=None,
    payload=None,
    ts="2026-03-08T00:00:00+00:00",
):
    return {
        "seq": seq,
        "event_id": event_id or f"legacy-{seq}",
        "ts": ts,
        "kind": kind,
        "session_id": session_id,
        "payload": payload or {},
    }


def _valid_event(
    *,
    seq=1,
    tx_id=1,
    ticket_id="p4-t2",
    event_type="tx.begin",
    phase="in-progress",
    step_id="p4-t2-s1",
    session_id="s1",
    payload=None,
):
    if payload is None:
        payload = {"ticket_id": ticket_id, "ticket_title": ticket_id}
    return {
        "seq": seq,
        "event_id": f"evt-{seq}",
        "ts": "2026-03-08T00:00:00+00:00",
        "project_root": "test-root",
        "tx_id": tx_id,
        "ticket_id": ticket_id,
        "event_type": event_type,
        "phase": phase,
        "step_id": step_id,
        "actor": {"agent_id": "a1"},
        "session_id": session_id,
        "payload": payload,
    }


def test_rebuild_tx_state_requires_event_log(repo_context, state_rebuilder):
    result = state_rebuilder.rebuild_tx_state()

    assert result["ok"] is False
    assert result["reason"] == "tx_event_log missing"


def test_rebuild_tx_state_accepts_empty_event_log(repo_context, state_rebuilder):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = state_rebuilder.rebuild_tx_state()

    assert result["ok"] is True
    assert result["source"] == "rebuild"
    assert result["last_applied_seq"] == 0
    assert result["state"]["active_tx"] is None
    assert result["state"]["status"] is None
    assert result["state"]["next_action"] == "tx.begin"
    assert result["state"]["integrity"]["active_tx_source"] == "none"
    assert result["state"]["integrity"]["drift_detected"] is False


def test_read_tx_event_log_filters_by_seq_range(repo_context, state_rebuilder):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.step.enter",
            payload={"step_id": "p4-t2-s2", "description": "step"},
        ),
    )

    result = state_rebuilder.read_tx_event_log(start_seq=1, end_seq=2)

    assert [event["seq"] for event in result["events"]] == [2]
    assert result["invalid_lines"] == 0


def test_read_tx_event_log_counts_invalid_lines(repo_context, state_rebuilder):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps(["not", "a", "dict"]),
                json.dumps({"seq": "bad"}),
                json.dumps(_valid_event(seq=1)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.read_tx_event_log(start_seq=0)

    assert result["invalid_lines"] == 3
    assert [event["seq"] for event in result["events"]] == [1]


def test_read_recent_tx_events_returns_tail(repo_context, state_rebuilder):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.step.enter",
            payload={"step_id": "p4-t2-s2", "description": "step 2"},
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=3,
            event_type="tx.step.enter",
            payload={"step_id": "p4-t2-s3", "description": "step 3"},
        ),
    )

    result = state_rebuilder.read_recent_tx_events(2)

    assert [event["seq"] for event in result] == [2, 3]


def test_rebuild_tx_state_uses_materialized_when_intact(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(_valid_event(seq=1)) + "\n",
        encoding="utf-8",
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_state_save(rebuild["state"])

    rebuild_again = state_rebuilder.rebuild_tx_state()

    assert rebuild_again["ok"] is True
    assert rebuild_again["source"] == "materialized"
    assert rebuild_again["state"]["integrity"]["drift_detected"] is False
    assert rebuild_again["state"]["integrity"]["active_tx_source"] == "materialized"


def test_rebuild_tx_state_keeps_minimal_active_tx_identity(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.step.enter",
            payload={"step_id": "p4-t2-s1", "description": "task started"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "p4-t2"
    assert set(active_tx.keys()) <= {"tx_id", "ticket_id", "phase"}


def test_rebuild_tx_state_committed_next_action_is_end_done(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.verify.start",
            phase="checking",
            payload={"command": "verify"},
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=3,
            event_type="tx.verify.pass",
            phase="verified",
            payload={"ok": True, "returncode": 0, "summary": "ok"},
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=4,
            event_type="tx.commit.start",
            phase="verified",
            payload={
                "message": "commit",
                "branch": "main",
                "diff_summary": "diff",
            },
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=5,
            event_type="tx.commit.done",
            phase="committed",
            payload={
                "sha": "abc123",
                "branch": "main",
                "diff_summary": "diff",
            },
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["status"] == "committed"
    assert rebuild["state"]["next_action"] == "tx.end.done"


def test_rebuild_tx_state_truncates_on_invalid_event_shape(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(repo_context, {"seq": 2, "event_id": "bad", "tx_id": 1})

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_marks_drift_for_duplicate_begin(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.begin",
            payload={"ticket_id": "p4-t2", "ticket_title": "duplicate"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "duplicate tx.begin"
    assert rebuild["state"]["rebuild_invalid_seq"] == 2
    assert rebuild["state"]["integrity"]["drift_detected"] is True
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"


def test_truncate_text_handles_limits(state_rebuilder):
    assert state_rebuilder._truncate_text(None) is None
    assert state_rebuilder._truncate_text("abc", limit=0) == ""
    assert state_rebuilder._truncate_text("abc", limit=10) == "abc"
    assert state_rebuilder._truncate_text("abcdef", limit=3) == "abc...(truncated)"


def test_resolve_path_uses_default_and_relative(repo_context, state_rebuilder):
    default = repo_context.tx_state

    assert state_rebuilder.resolve_path(None, default) == default
    assert state_rebuilder.resolve_path("nested/file.json", default) == (
        repo_context.get_repo_root() / "nested/file.json"
    )


def test_init_active_tx_and_init_tx_state(state_rebuilder):
    active_tx = state_rebuilder._init_active_tx(7, "p7-t1", "in-progress", "step-1")
    tx_state = state_rebuilder._init_tx_state()

    assert active_tx == {
        "tx_id": 7,
        "ticket_id": "p7-t1",
        "phase": "in-progress",
        "_last_event_seq": -1,
    }
    assert tx_state["schema_version"] == "0.4.0"
    assert tx_state["active_tx"] is None
    assert tx_state["next_action"] == "tx.begin"
    assert tx_state["integrity"]["active_tx_source"] == "none"


def test_compute_state_hash_ignores_updated_at_and_runtime_fields(state_rebuilder):
    state_a = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p1-t1",
            "phase": "in-progress",
            "_last_event_seq": 10,
            "_terminal": True,
        },
        "status": "in-progress",
        "next_action": "tx.verify.start",
        "verify_state": None,
        "commit_state": None,
        "semantic_summary": "summary",
        "last_applied_seq": 10,
        "integrity": {
            "state_hash": "old",
            "rebuilt_from_seq": 10,
            "drift_detected": False,
            "active_tx_source": "materialized",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }
    state_b = json.loads(json.dumps(state_a))
    state_b["updated_at"] = "2026-03-09T00:00:00+00:00"
    state_b["active_tx"]["_last_event_seq"] = 999
    state_b["active_tx"]["_terminal"] = False
    state_b["integrity"]["state_hash"] = "other"

    assert state_rebuilder._compute_state_hash(
        state_a
    ) == state_rebuilder._compute_state_hash(state_b)


def test_validate_tx_event_rejects_missing_required_fields(state_rebuilder):
    valid, reason = state_rebuilder._validate_tx_event({"seq": 1})

    assert valid is False
    assert reason == "missing tx_id"


def test_validate_tx_event_rejects_unknown_event_type(state_rebuilder):
    valid, reason = state_rebuilder._validate_tx_event(
        {
            "seq": 1,
            "tx_id": 1,
            "ticket_id": "p1-t1",
            "event_type": "tx.unknown",
            "phase": "in-progress",
            "step_id": "step-1",
            "actor": {"tool": "test"},
            "session_id": "s1",
            "payload": {},
        }
    )

    assert valid is False
    assert reason == "unknown event_type"


def test_intent_state_rank_returns_negative_for_invalid_value(state_rebuilder):
    assert state_rebuilder._intent_state_rank(None) == -1
    assert state_rebuilder._intent_state_rank("unknown") == -1
    assert state_rebuilder._intent_state_rank("planned") >= 0


def test_validate_tx_event_payload_covers_multiple_event_types(state_rebuilder):
    valid_begin, begin_reason = state_rebuilder._validate_tx_event_payload(
        "tx.begin",
        {"ticket_id": "p1-t1"},
        "step-1",
    )
    valid_verify_pass, verify_pass_reason = state_rebuilder._validate_tx_event_payload(
        "tx.verify.pass",
        {"ok": True},
        "step-1",
    )
    valid_verify_fail, verify_fail_reason = state_rebuilder._validate_tx_event_payload(
        "tx.verify.fail",
        {"ok": False},
        "step-1",
    )
    valid_commit_fail, commit_fail_reason = state_rebuilder._validate_tx_event_payload(
        "tx.commit.fail",
        {"error": "boom"},
        "step-1",
    )
    valid_blocked, blocked_reason = state_rebuilder._validate_tx_event_payload(
        "tx.end.blocked",
        {"reason": "blocked"},
        "step-1",
    )
    invalid_step, invalid_step_reason = state_rebuilder._validate_tx_event_payload(
        "tx.step.enter",
        {},
        "step-1",
    )

    assert valid_begin is True
    assert begin_reason == "missing payload.ticket_id"
    assert valid_verify_pass is True
    assert verify_pass_reason == "payload.ok must be true"
    assert valid_verify_fail is True
    assert verify_fail_reason == "payload.ok must be false"
    assert valid_commit_fail is True
    assert commit_fail_reason == "missing payload.error"
    assert valid_blocked is True
    assert blocked_reason == "missing payload.reason"
    assert invalid_step is False
    assert invalid_step_reason == "missing payload.step_id"


def test_validate_tx_event_invariants_rejects_duplicate_begin_without_terminal(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    first = {
        "event_type": "tx.begin",
        "payload": {"ticket_id": "p1-t1"},
        "step_id": "none",
    }
    second = {
        "event_type": "tx.begin",
        "payload": {"ticket_id": "p1-t1"},
        "step_id": "none",
    }

    valid_first, _ = state_rebuilder._validate_tx_event_invariants(context, first)
    valid_second, reason_second = state_rebuilder._validate_tx_event_invariants(
        context, second
    )

    assert valid_first is True
    assert valid_second is False
    assert reason_second == "duplicate tx.begin"


def test_validate_tx_event_invariants_allows_begin_after_terminal(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["terminal"] = True
    context["steps"] = {"old"}
    context["intent_states"] = {"a.py": "planned"}
    context["verify_started_steps"] = {"old"}
    context["verify_passed"] = True
    context["commit_started"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.begin",
            "payload": {"ticket_id": "p2-t1"},
            "step_id": "none",
        },
    )

    assert valid is True
    assert reason == ""
    assert context["terminal"] is False
    assert context["steps"] == set()
    assert context["intent_states"] == {}
    assert context["verify_started_steps"] == set()
    assert context["verify_passed"] is False
    assert context["commit_started"] is False


def test_validate_tx_event_invariants_rejects_event_before_begin(state_rebuilder):
    context = state_rebuilder._init_tx_context()

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.step.enter",
            "payload": {"step_id": "step-1"},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "tx.begin required"


def test_validate_tx_event_invariants_rejects_event_after_terminal(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["terminal"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.step.enter",
            "payload": {"step_id": "step-1"},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "event after terminal"


def test_validate_tx_event_invariants_rejects_unknown_intent_update(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.update",
            "payload": {"path": "missing.py", "state": "started"},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "file intent missing for path"


def test_validate_tx_event_invariants_rejects_verify_without_start(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.verify.pass",
            "payload": {"ok": True},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "verify result requires verify.start"


def test_validate_tx_event_invariants_rejects_commit_without_verify(state_rebuilder):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.commit.start",
            "payload": {
                "message": "msg",
                "branch": "main",
                "diff_summary": "diff",
            },
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "commit.start requires verify.pass"


def test_update_semantic_summary_covers_multiple_branches(state_rebuilder):
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.file_intent.add",
            {"path": "a.py", "operation": "update"},
            "step-1",
        )
        == "Planned update for a.py"
    )
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.file_intent.update",
            {"path": "a.py", "state": "started"},
            "step-1",
        )
        == "Updated intent for a.py to started"
    )
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.file_intent.complete",
            {"path": "a.py"},
            "step-1",
        )
        == "Completed intent for a.py"
    )
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.verify.fail",
            {},
            "step-1",
        )
        == "Verification failed"
    )
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.commit.fail",
            {},
            "step-1",
        )
        == "Commit failed"
    )
    assert (
        state_rebuilder._update_semantic_summary(
            "tx.end.done",
            {},
            "step-1",
        )
        == "Transaction ended"
    )


def test_apply_tx_event_to_state_updates_begin_phase_and_seq(state_rebuilder):
    active_tx = {"tx_id": 1, "ticket_id": "old", "phase": "planned"}
    event = {
        "event_type": "tx.begin",
        "tx_id": 2,
        "ticket_id": "p2-t1",
        "phase": "in-progress",
        "seq": 9,
    }

    result = state_rebuilder._apply_tx_event_to_state(active_tx, event)

    assert result["tx_id"] == 2
    assert result["ticket_id"] == "p2-t1"
    assert result["phase"] == "in-progress"
    assert result["_last_event_seq"] == 9


def test_derive_next_action_covers_status_variants(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status="checking",
            verify_state={"status": "failed"},
            commit_state=None,
            active_tx=None,
            semantic_summary=None,
        )
        == "fix and re-verify"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="verified",
            verify_state={"status": "passed"},
            commit_state={"status": "not_started"},
            active_tx=None,
            semantic_summary=None,
        )
        == "tx.commit.start"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="blocked",
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary=None,
        )
        == "tx.end.blocked"
    )
    assert (
        state_rebuilder._derive_next_action(
            status=None,
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary=None,
        )
        == "tx.begin"
    )


def test_tx_state_integrity_ok_rejects_invalid_shapes(state_rebuilder):
    state = state_rebuilder._init_tx_state()
    state["last_applied_seq"] = 2
    state["integrity"]["rebuilt_from_seq"] = 2
    state["integrity"]["active_tx_source"] = "none"
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)

    assert state_rebuilder._tx_state_integrity_ok(state, 2) is True

    broken = json.loads(json.dumps(state))
    broken["next_action"] = "wrong"
    assert state_rebuilder._tx_state_integrity_ok(broken, 2) is False

    active = state_rebuilder._init_tx_state()
    active["active_tx"] = {
        "tx_id": 1,
        "ticket_id": "p1-t1",
        "phase": "in-progress",
        "_last_event_seq": 2,
    }
    active["status"] = "in-progress"
    active["next_action"] = "tx.verify.start"
    active["semantic_summary"] = "Started transaction p1-t1"
    active["last_applied_seq"] = 2
    active["integrity"]["rebuilt_from_seq"] = 2
    active["integrity"]["active_tx_source"] = "active_candidate"
    active["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(active)

    assert state_rebuilder._tx_state_integrity_ok(active, 2) is True

    active_broken = json.loads(json.dumps(active))
    active_broken["active_tx"]["extra"] = "nope"
    assert state_rebuilder._tx_state_integrity_ok(active_broken, 2) is False


def test_parse_iso_ts_and_week_start_utc(state_rebuilder):
    parsed = state_rebuilder.parse_iso_ts("2026-03-08T00:00:00Z")
    invalid = state_rebuilder.parse_iso_ts("bad")
    week_start = state_rebuilder.week_start_utc(
        datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
    )

    assert parsed == datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc)
    assert invalid is None
    assert week_start == datetime(2026, 3, 9, 0, 0, 0, tzinfo=timezone.utc)


def test_read_first_event_with_ts_skips_invalid_lines(repo_context, state_rebuilder):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text(
        "\n".join(
            [
                "{bad",
                json.dumps(["not-a-dict"]),
                json.dumps({"ts": "bad"}),
                json.dumps(
                    {
                        "ts": "2026-03-08T00:00:00+00:00",
                        "kind": "session.start",
                        "session_id": "s1",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.read_first_event_with_ts(repo_context.journal)

    assert result is not None
    record, ts = result
    assert record["kind"] == "session.start"
    assert ts == datetime(2026, 3, 8, 0, 0, 0, tzinfo=timezone.utc)


def test_rotate_journal_if_prev_week_returns_no_last_week_events(
    repo_context, state_rebuilder
):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text(
        json.dumps(
            {
                "ts": "2030-01-07T00:00:00+00:00",
                "kind": "session.start",
                "session_id": "s1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.rotate_journal_if_prev_week()

    assert result["ok"] is True
    assert result["rotated"] is False


def test_init_replay_state_normalizes_seed_types(state_rebuilder):
    state = state_rebuilder.init_replay_state(
        {
            "task_id": None,
            "task_title": None,
            "task_status": None,
            "plan_steps": "bad",
            "artifact_summary": None,
            "last_verification": [],
            "failure_reason": None,
            "replay_warnings": {},
            "applied_event_ids": "bad",
        }
    )

    assert state["task_id"] == ""
    assert state["task_title"] == ""
    assert state["task_status"] == ""
    assert state["plan_steps"] == []
    assert state["artifact_summary"] == ""
    assert state["last_verification"] == {}
    assert state["failure_reason"] == ""
    assert state["replay_warnings"]["invalid_lines"] == 0
    assert state["replay_warnings"]["dropped_events"] == 0
    assert state["applied_event_ids"] == []


def test_select_target_session_id_prefers_session_start(state_rebuilder):
    events = [
        _legacy_event(seq=1, kind="task.start", session_id="s1"),
        _legacy_event(seq=2, kind="session.start", session_id="s2"),
        _legacy_event(seq=3, kind="task.update", session_id="s3"),
    ]

    result = state_rebuilder.select_target_session_id(events, None)

    assert result == "s2"


def test_append_applied_event_id_trims_old_entries(state_rebuilder):
    state = {"applied_event_ids": ["a", "b"]}

    state_rebuilder.append_applied_event_id(state, "c", max_size=2)

    assert state["applied_event_ids"] == ["b", "c"]


def test_apply_event_to_state_covers_legacy_kinds(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)

    state_rebuilder.apply_event_to_state(
        state, _legacy_event(seq=1, kind="session.start", session_id="s1")
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=2,
            kind="task.created",
            payload={"task_id": "p1-t1", "title": "Task", "status": "planned"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=3,
            kind="task.progress",
            payload={"status": "checking", "note": "progress note"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=4,
            kind="task.blocked",
            payload={"reason": "blocked reason", "note": "blocked note"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=5, kind="plan.start", payload={"steps": ["a", "b"]}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=6, kind="plan.step", payload={"step": "c"}),
    )
    state_rebuilder.apply_event_to_state(state, _legacy_event(seq=7, kind="plan.end"))
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=8, kind="artifact.summary", payload={"summary": "artifact"}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=9, kind="verify.start"),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=10,
            kind="verify.end",
            payload={
                "ok": False,
                "returncode": 1,
                "stdout": "x" * 600,
                "stderr": "stderr text",
            },
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=11,
            kind="verify.result",
            payload={"ok": False, "reason": "verify failed"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=12, kind="commit.start", payload={"message": "commit msg"}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=13, kind="commit.end", payload={"sha": "abc123"}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=14,
            kind="file.edit",
            payload={"action": "updated", "path": "tests/test_x.py"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=15, kind="tool.result", payload={"ok": False, "error": "boom"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=16, kind="error", payload={"message": "fatal"}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=17,
            kind="task.end",
            payload={"summary": "done summary", "next_action": "next"},
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=18, kind="session.end"),
    )

    assert state["session_id"] == "s1"
    assert state["task_id"] == "p1-t1"
    assert state["task_title"] == "Task"
    assert state["artifact_summary"] == "artifact"
    assert state["verification_status"] == "failed"
    assert state["last_commit"] == "abc123"
    assert state["last_error"] == "fatal"
    assert state["next_step"] == "next"
    assert state["current_task"] == ""
    assert state["failure_reason"] == "verify failed"


def test_replay_events_to_state_filters_by_target_session_and_dedupes(state_rebuilder):
    events = [
        _legacy_event(seq=1, kind="session.start", session_id="s1", event_id="e1"),
        _legacy_event(
            seq=2,
            kind="task.start",
            session_id="s1",
            event_id="e2",
            payload={"title": "Task", "task_id": "p1-t1"},
        ),
        _legacy_event(
            seq=3,
            kind="task.update",
            session_id="s2",
            event_id="e3",
            payload={"status": "checking", "note": "other session"},
        ),
        _legacy_event(
            seq=4,
            kind="task.update",
            session_id="s1",
            event_id="e2",
            payload={"status": "checking", "note": "duplicate"},
        ),
    ]

    result = state_rebuilder.replay_events_to_state(
        {"applied_event_ids": []},
        events,
        preferred_session_id="s1",
        invalid_lines=2,
    )

    assert result["session_id"] == "s1"
    assert result["current_task"] == "Task"
    assert result["replay_warnings"]["invalid_lines"] == 2
    assert result["replay_warnings"]["dropped_events"] == 1


def test_replay_events_to_state_returns_seed_when_no_target_session(state_rebuilder):
    result = state_rebuilder.replay_events_to_state(None, [], preferred_session_id=None)

    assert result["session_id"] == ""
    assert result["current_task"] == ""


def test_rebuild_tx_state_marks_drift_for_invalid_commit_order(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.commit.start",
            phase="verified",
            payload={
                "message": "commit",
                "branch": "main",
                "diff_summary": "diff",
            },
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "commit.start requires verify.pass"
    assert rebuild["state"]["integrity"]["drift_detected"] is True


def test_rebuild_tx_state_prefers_latest_non_terminal_transaction(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        _valid_event(seq=1, tx_id=1, ticket_id="p1-t1"),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            tx_id=1,
            ticket_id="p1-t1",
            event_type="tx.end.done",
            phase="done",
            payload={"summary": "done"},
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(seq=3, tx_id=2, ticket_id="p2-t3"),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=4,
            tx_id=2,
            ticket_id="p2-t3",
            event_type="tx.step.enter",
            payload={"step_id": "p2-t3-s1", "description": "active"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["active_tx"]["tx_id"] == 2
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p2-t3"
    assert rebuild["state"]["integrity"]["active_tx_source"] == "active_candidate"


def test_rebuild_tx_state_returns_idle_when_only_terminal_transactions_exist(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.end.done",
            phase="done",
            payload={"summary": "done"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"
    assert rebuild["state"]["integrity"]["active_tx_source"] == "none"


def test_tx_state_integrity_ok_accepts_valid_minimal_state(state_rebuilder):
    state = {
        "schema_version": "0.4.0",
        "active_tx": {"tx_id": 1, "ticket_id": "p4-t2", "phase": "in-progress"},
        "status": "in-progress",
        "next_action": "tx.verify.start",
        "semantic_summary": "Started transaction p4-t2",
        "verify_state": None,
        "commit_state": None,
        "last_applied_seq": 1,
        "integrity": {
            "state_hash": "",
            "rebuilt_from_seq": 1,
            "drift_detected": False,
            "active_tx_source": "active_candidate",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }
    state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(state)

    assert state_rebuilder._tx_state_integrity_ok(state, 1) is True


def test_tx_state_integrity_ok_rejects_bad_hash(state_rebuilder):
    state = {
        "schema_version": "0.4.0",
        "active_tx": {"tx_id": 1, "ticket_id": "p4-t2", "phase": "in-progress"},
        "status": "in-progress",
        "next_action": "tx.verify.start",
        "semantic_summary": "Started transaction p4-t2",
        "verify_state": None,
        "commit_state": None,
        "last_applied_seq": 1,
        "integrity": {
            "state_hash": "bad",
            "rebuilt_from_seq": 1,
            "drift_detected": False,
            "active_tx_source": "active_candidate",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }

    assert state_rebuilder._tx_state_integrity_ok(state, 1) is False


def test_validate_tx_event_payload_covers_remaining_event_types(state_rebuilder):
    valid_add, add_reason = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "src/example.py",
            "operation": "update",
            "purpose": "exercise branch",
            "planned_step": "step-1",
            "state": "planned",
        },
        "step-1",
    )
    invalid_add, invalid_add_reason = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.add",
        {
            "path": "src/example.py",
            "operation": "invalid",
            "purpose": "exercise branch",
            "planned_step": "step-1",
            "state": "planned",
        },
        "step-1",
    )
    valid_update, update_reason = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.update",
        {"path": "src/example.py", "state": "verified"},
        "step-1",
    )
    invalid_update, invalid_update_reason = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.update",
        {"path": "src/example.py", "state": "planned"},
        "step-1",
    )
    valid_complete, complete_reason = state_rebuilder._validate_tx_event_payload(
        "tx.file_intent.complete",
        {"path": "src/example.py", "state": "verified"},
        "step-1",
    )
    invalid_complete, invalid_complete_reason = (
        state_rebuilder._validate_tx_event_payload(
            "tx.file_intent.complete",
            {"path": "src/example.py", "state": "started"},
            "step-1",
        )
    )
    valid_commit_start, commit_start_reason = (
        state_rebuilder._validate_tx_event_payload(
            "tx.commit.start",
            {
                "message": "msg",
                "branch": "main",
                "diff_summary": "1 file changed",
            },
            "step-1",
        )
    )
    invalid_commit_start, invalid_commit_start_reason = (
        state_rebuilder._validate_tx_event_payload(
            "tx.commit.start",
            {"message": "msg", "branch": "main"},
            "step-1",
        )
    )
    valid_commit_done, commit_done_reason = state_rebuilder._validate_tx_event_payload(
        "tx.commit.done",
        {"sha": "abc123", "branch": "main", "diff_summary": "1 file changed"},
        "step-1",
    )
    invalid_commit_done, invalid_commit_done_reason = (
        state_rebuilder._validate_tx_event_payload(
            "tx.commit.done",
            {"branch": "main", "diff_summary": "1 file changed"},
            "step-1",
        )
    )
    valid_end_done, end_done_reason = state_rebuilder._validate_tx_event_payload(
        "tx.end.done",
        {"summary": "completed"},
        "step-1",
    )
    valid_user_intent, user_intent_reason = state_rebuilder._validate_tx_event_payload(
        "tx.user_intent.set",
        {"user_intent": "resume work"},
        "step-1",
    )
    invalid_user_intent, invalid_user_intent_reason = (
        state_rebuilder._validate_tx_event_payload(
            "tx.user_intent.set",
            {},
            "step-1",
        )
    )

    assert valid_add is True
    assert add_reason == ""
    assert invalid_add is False
    assert invalid_add_reason == "payload.operation is invalid"
    assert valid_update is True
    assert update_reason == ""
    assert invalid_update is False
    assert (
        invalid_update_reason == "payload.state must be started, applied, or verified"
    )
    assert valid_complete is True
    assert complete_reason == ""
    assert invalid_complete is False
    assert invalid_complete_reason == "payload.state must be verified"
    assert valid_commit_start is True
    assert commit_start_reason == ""
    assert invalid_commit_start is False
    assert invalid_commit_start_reason == "missing payload.diff_summary"
    assert valid_commit_done is True
    assert commit_done_reason == ""
    assert invalid_commit_done is False
    assert invalid_commit_done_reason == "missing payload.sha"
    assert valid_end_done is True
    assert end_done_reason == "missing payload.summary"
    assert valid_user_intent is True
    assert user_intent_reason == "missing payload.user_intent"
    assert invalid_user_intent is False
    assert invalid_user_intent_reason == "missing payload.user_intent"


def test_validate_tx_event_invariants_rejects_missing_planned_step_reference(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["steps"] = {"step-1"}

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "payload": {
                "path": "src/example.py",
                "operation": "update",
                "purpose": "exercise branch",
                "planned_step": "step-2",
                "state": "planned",
            },
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "planned_step must reference a prior step"


def test_validate_tx_event_invariants_rejects_duplicate_file_intent_add(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["steps"] = {"step-1"}
    first_event = {
        "event_type": "tx.file_intent.add",
        "payload": {
            "path": "src/example.py",
            "operation": "update",
            "purpose": "exercise branch",
            "planned_step": "step-1",
            "state": "planned",
        },
        "step_id": "step-1",
    }

    valid_first, _ = state_rebuilder._validate_tx_event_invariants(context, first_event)
    valid_second, reason_second = state_rebuilder._validate_tx_event_invariants(
        context,
        first_event,
    )

    assert valid_first is True
    assert valid_second is False
    assert reason_second == "file intent already exists"


def test_validate_tx_event_invariants_rejects_non_monotonic_file_intent_state(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["steps"] = {"step-1"}
    context["intent_states"] = {"src/example.py": "applied"}
    context["intent_steps"] = {"src/example.py": "step-1"}

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.update",
            "payload": {"path": "src/example.py", "state": "started"},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "file intent state must be monotonic"


def test_validate_tx_event_invariants_rejects_verify_start_before_applied_intent(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True
    context["intent_steps"] = {"src/example.py": "step-1"}
    context["intent_states"] = {"src/example.py": "started"}

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.verify.start",
            "payload": {"command": "verify"},
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "verify.start requires applied intents"


def test_validate_tx_event_invariants_rejects_commit_result_without_start(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()
    context["seen_begin"] = True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.commit.done",
            "payload": {
                "sha": "abc123",
                "branch": "main",
                "diff_summary": "1 file changed",
            },
            "step_id": "step-1",
        },
    )

    assert valid is False
    assert reason == "commit result requires commit.start"


def test_rotate_journal_if_prev_week_archives_last_week_events(
    repo_context, state_rebuilder
):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-03-03T12:00:00+00:00",
                        "kind": "session.start",
                        "session_id": "s-old",
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-03-09T01:00:00+00:00",
                        "kind": "task.update",
                        "session_id": "s-keep",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    original_week_start_utc = state_rebuilder.week_start_utc
    state_rebuilder.week_start_utc = lambda dt: (
        datetime(2026, 3, 2, 0, 0, 0, tzinfo=timezone.utc)
        if dt == datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc)
        else datetime(2026, 3, 9, 0, 0, 0, tzinfo=timezone.utc)
    )
    try:
        result = state_rebuilder.rotate_journal_if_prev_week()
    finally:
        state_rebuilder.week_start_utc = original_week_start_utc

    assert result["ok"] is True
    assert result["rotated"] is True
    assert result["archived"] == 1
    assert result["kept"] == 1

    archive_path = repo_context.journal.with_name("journal.20260302-20260308.jsonl")
    assert result["archive"] == str(archive_path)
    assert archive_path.exists()

    archived_lines = [
        json.loads(line)
        for line in archive_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kept_lines = [
        json.loads(line)
        for line in repo_context.journal.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert archived_lines == [
        {
            "ts": "2026-03-03T12:00:00+00:00",
            "kind": "session.start",
            "session_id": "s-old",
        }
    ]
    assert kept_lines == [
        {
            "ts": "2026-03-09T01:00:00+00:00",
            "kind": "task.update",
            "session_id": "s-keep",
        }
    ]


def test_rebuild_tx_state_drops_duplicate_event_ids(repo_context, state_rebuilder):
    first = _valid_event(seq=1)
    first["event_id"] = "dup-1"
    _append_raw_tx_event(repo_context, first)

    second = _valid_event(
        seq=2,
        event_type="tx.step.enter",
        payload={"step_id": "p4-t2-s2", "description": "duplicate"},
    )
    second["event_id"] = "dup-1"
    _append_raw_tx_event(repo_context, second)

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["dropped_events"] == 1
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["active_tx"]["tx_id"] == 1


def test_rebuild_tx_state_handles_materialized_idle_state(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(_valid_event(seq=1)) + "\n",
        encoding="utf-8",
    )
    idle_state = state_rebuilder._init_tx_state()
    idle_state["last_applied_seq"] = 1
    idle_state["integrity"]["rebuilt_from_seq"] = 1
    idle_state["integrity"]["active_tx_source"] = "none"
    idle_state["integrity"]["state_hash"] = state_rebuilder._compute_state_hash(
        idle_state
    )
    state_store.tx_state_save(idle_state)

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["source"] == "materialized"
    assert rebuild["state"]["active_tx"] is None
    assert rebuild["state"]["status"] is None
    assert rebuild["state"]["next_action"] == "tx.begin"
    assert rebuild["state"]["verify_state"] is None
    assert rebuild["state"]["commit_state"] is None
    assert rebuild["state"]["integrity"]["active_tx_source"] == "none"


def test_rebuild_tx_state_invalid_payload_with_non_integer_tx_id_does_not_prune_known_tx(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1, tx_id=7, ticket_id="p7-t1"))
    invalid_event = {
        "seq": 2,
        "event_id": "evt-2",
        "ts": "2026-03-08T00:00:01+00:00",
        "project_root": "test-root",
        "tx_id": "bad",
        "ticket_id": "p7-t1",
        "event_type": "tx.step.enter",
        "phase": "in-progress",
        "step_id": "p7-t1-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"step_id": "p7-t1-s1", "description": "bad"},
    }
    _append_raw_tx_event(repo_context, invalid_event)

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1
    assert rebuild["state"]["rebuild_warning"] == "missing tx_id"
    assert rebuild["state"]["rebuild_invalid_event"] == invalid_event
    assert rebuild["state"]["active_tx"] == {"tx_id": 7, "ticket_id": "p7-t1"}
    assert rebuild["state"]["rebuild_observed_mismatch"]["known_tx_ids"] == []


def test_rebuild_tx_state_uses_latest_matching_phase_when_active_phase_blank(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=1, phase="", payload={"ticket_id": "p4-t2", "ticket_title": "p4-t2"}
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.step.enter",
            phase="checking",
            payload={"step_id": "p4-t2-s1", "description": "checking"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["status"] == "checking"
    assert rebuild["state"]["active_tx"]["ticket_id"] == "p4-t2"


def test_rebuild_tx_state_uses_fallback_semantic_summary_for_unmapped_event(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            event_type="tx.user_intent.set",
            payload={"user_intent": "resume p4-t2"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["state"]["semantic_summary"] == "Rebuilt state from tx event log."


def test_rebuild_tx_state_marks_drift_when_selected_active_tx_lags_latest_seq(
    repo_context, state_rebuilder
):
    _append_raw_tx_event(repo_context, _valid_event(seq=1, tx_id=1, ticket_id="p1-t1"))
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=2,
            tx_id=2,
            ticket_id="p2-t1",
            event_type="tx.begin",
            payload={"ticket_id": "p2-t1", "ticket_title": "p2-t1"},
        ),
    )
    _append_raw_tx_event(
        repo_context,
        _valid_event(
            seq=3,
            tx_id=2,
            ticket_id="p2-t1",
            event_type="tx.end.done",
            phase="done",
            payload={"summary": "done"},
        ),
    )

    rebuild = state_rebuilder.rebuild_tx_state()

    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 3
    assert rebuild["state"]["integrity"]["drift_detected"] is True
    assert (
        rebuild["state"]["rebuild_warning"]
        == "selected active transaction does not match the latest canonical event sequence"
    )
    assert rebuild["state"]["rebuild_observed_mismatch"]["active_tx_id"] == 1
    assert rebuild["state"]["rebuild_observed_mismatch"]["last_applied_seq"] == 3


def test_parse_iso_ts_rejects_non_iso_value(state_rebuilder):
    assert state_rebuilder.parse_iso_ts("not-a-timestamp") is None


def test_read_first_event_with_ts_returns_none_for_missing_path(
    state_rebuilder, repo_context
):
    assert (
        state_rebuilder.read_first_event_with_ts(
            repo_context.get_repo_root() / "missing.jsonl"
        )
        is None
    )


def test_rotate_journal_if_prev_week_handles_missing_and_invalid_journal(
    repo_context, state_rebuilder
):
    missing = state_rebuilder.rotate_journal_if_prev_week()
    assert missing["ok"] is False
    assert missing["reason"] == "journal not found"

    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text("{bad json}\n", encoding="utf-8")

    invalid = state_rebuilder.rotate_journal_if_prev_week()
    assert invalid["ok"] is False
    assert invalid["reason"] == "no valid journal timestamps"


def test_rotate_journal_if_prev_week_counts_invalid_lines(
    repo_context, state_rebuilder
):
    repo_context.journal.parent.mkdir(parents=True, exist_ok=True)
    repo_context.journal.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-03-03T12:00:00+00:00",
                        "kind": "session.start",
                        "session_id": "s-old",
                    }
                ),
                "{bad json}",
                json.dumps(["not-a-dict"]),
                json.dumps({"ts": 123, "kind": "task.update"}),
                json.dumps({"ts": "bad", "kind": "task.update"}),
                json.dumps(
                    {
                        "ts": "2026-03-09T01:00:00+00:00",
                        "kind": "task.update",
                        "session_id": "s-keep",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    original_week_start_utc = state_rebuilder.week_start_utc
    state_rebuilder.week_start_utc = lambda dt: (
        datetime(2026, 3, 2, 0, 0, 0, tzinfo=timezone.utc)
        if dt == datetime(2026, 3, 3, 12, 0, 0, tzinfo=timezone.utc)
        else datetime(2026, 3, 9, 0, 0, 0, tzinfo=timezone.utc)
    )
    try:
        result = state_rebuilder.rotate_journal_if_prev_week()
    finally:
        state_rebuilder.week_start_utc = original_week_start_utc

    assert result["ok"] is True
    assert result["rotated"] is True
    assert result["invalid_json_lines"] == 2
    assert result["invalid_ts"] == 2
    assert result["archived"] == 1
    assert result["kept"] == 5


def test_select_target_session_id_prefers_explicit_value(state_rebuilder):
    events = [_legacy_event(seq=1, kind="session.start", session_id="s1")]

    assert (
        state_rebuilder.select_target_session_id(events, "preferred-s") == "preferred-s"
    )


def test_select_target_session_id_returns_latest_any_when_no_session_start(
    state_rebuilder,
):
    events = [
        _legacy_event(seq=1, kind="task.start", session_id="s1"),
        _legacy_event(seq=2, kind="task.update", session_id="s2"),
    ]

    assert state_rebuilder.select_target_session_id(events, None) == "s2"


def test_append_applied_event_id_initializes_missing_list(state_rebuilder):
    state = {}

    state_rebuilder.append_applied_event_id(state, "e1", max_size=2)

    assert state["applied_event_ids"] == ["e1"]


def test_apply_event_to_state_handles_remaining_legacy_branches(state_rebuilder):
    state = state_rebuilder.init_replay_state(None)

    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=1, kind="task.start", payload={"title": "Task", "task_id": "p1-t1"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=2, kind="task.update", payload={"status": "checking", "note": "update"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=3, kind="verify.end", payload={"ok": False, "stderr": "stderr boom"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=4, kind="verify.result", payload={"ok": False, "stderr": "stderr 2"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=5, kind="commit.end", payload={"summary": "commit summary"}),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(
            seq=6, kind="tool.result", payload={"ok": False, "error": "tool boom"}
        ),
    )
    state_rebuilder.apply_event_to_state(
        state,
        _legacy_event(seq=7, kind="file.edit", payload={"action": "updated"}),
    )

    assert state["current_task"] == "Task"
    assert state["current_phase"] == "checking"
    assert state["failure_reason"] == "stderr 2"
    assert state["last_commit"] == "commit summary"
    assert state["last_error"] == "tool boom"


def test_replay_events_to_state_sets_target_session_when_missing_in_seed(
    state_rebuilder,
):
    events = [
        _legacy_event(
            seq=1,
            kind="task.update",
            session_id="s1",
            event_id="e1",
            payload={"note": "note"},
        )
    ]

    result = state_rebuilder.replay_events_to_state(
        {}, events, preferred_session_id=None
    )

    assert result["session_id"] == "s1"


def test_derive_next_action_for_core_statuses(state_rebuilder):
    assert (
        state_rebuilder._derive_next_action(
            status=None,
            verify_state=None,
            commit_state=None,
            active_tx=None,
            semantic_summary=None,
        )
        == "tx.begin"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="in-progress",
            verify_state={"status": "not_started"},
            commit_state={"status": "not_started"},
            active_tx={},
            semantic_summary="",
        )
        == "tx.verify.start"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="checking",
            verify_state={"status": "failed"},
            commit_state={"status": "not_started"},
            active_tx={},
            semantic_summary="",
        )
        == "fix and re-verify"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="verified",
            verify_state={"status": "passed"},
            commit_state={"status": "not_started"},
            active_tx={},
            semantic_summary="",
        )
        == "tx.commit.start"
    )
    assert (
        state_rebuilder._derive_next_action(
            status="committed",
            verify_state={"status": "passed"},
            commit_state={"status": "passed"},
            active_tx={},
            semantic_summary="",
        )
        == "tx.end.done"
    )


def test_validate_tx_event_rejects_missing_fields(state_rebuilder):
    valid, reason = state_rebuilder._validate_tx_event({"seq": 1})

    assert valid is False
    assert reason == "missing tx_id"


def test_validate_tx_event_payload_checks_core_contracts(state_rebuilder):
    ok, _ = state_rebuilder._validate_tx_event_payload(
        "tx.begin", {"ticket_id": "p4-t2"}, "s1"
    )
    assert ok is True

    ok, reason = state_rebuilder._validate_tx_event_payload(
        "tx.commit.start",
        {"message": "commit", "branch": "main"},
        "s1",
    )
    assert ok is False
    assert reason == "missing payload.diff_summary"


def test_validate_tx_event_invariants_detects_duplicate_begin(state_rebuilder):
    context = state_rebuilder._init_tx_context()

    valid, _ = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.begin",
            "step_id": "none",
            "payload": {"ticket_id": "p4-t2"},
        },
    )
    assert valid is True

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.begin",
            "step_id": "none",
            "payload": {"ticket_id": "p4-t2"},
        },
    )
    assert valid is False
    assert reason == "duplicate tx.begin"


def test_validate_tx_event_invariants_requires_begin_before_other_events(
    state_rebuilder,
):
    context = state_rebuilder._init_tx_context()

    valid, reason = state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}},
    )

    assert valid is False
    assert reason == "tx.begin required"


def test_validate_tx_event_invariants_accepts_verify_flow(state_rebuilder):
    context = state_rebuilder._init_tx_context()

    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.begin",
            "step_id": "none",
            "payload": {"ticket_id": "p4-t2"},
        },
    ) == (True, "")
    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.step.enter", "step_id": "s1", "payload": {}},
    ) == (True, "")
    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.add",
            "step_id": "s1",
            "payload": {
                "path": "a.py",
                "operation": "update",
                "purpose": "tests",
                "planned_step": "s1",
                "state": "planned",
            },
        },
    ) == (True, "")
    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {
            "event_type": "tx.file_intent.update",
            "step_id": "s1",
            "payload": {"path": "a.py", "state": "applied"},
        },
    ) == (True, "")
    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.verify.start", "step_id": "s1", "payload": {}},
    ) == (True, "")
    assert state_rebuilder._validate_tx_event_invariants(
        context,
        {"event_type": "tx.verify.pass", "step_id": "s1", "payload": {"ok": True}},
    ) == (True, "")


def test_compute_state_hash_ignores_updated_at_and_internal_fields(state_rebuilder):
    state = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": 1,
            "ticket_id": "p4-t2",
            "phase": "in-progress",
            "_last_event_seq": 1,
            "_terminal": False,
        },
        "status": "in-progress",
        "next_action": "tx.verify.start",
        "semantic_summary": "Started transaction p4-t2",
        "verify_state": None,
        "commit_state": None,
        "last_applied_seq": 1,
        "integrity": {
            "state_hash": "",
            "rebuilt_from_seq": 1,
            "drift_detected": False,
            "active_tx_source": "active_candidate",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }

    first = state_rebuilder._compute_state_hash(state)
    state["updated_at"] = "2026-03-09T00:00:00+00:00"
    state["active_tx"]["_last_event_seq"] = 999
    state["active_tx"]["_terminal"] = True
    second = state_rebuilder._compute_state_hash(state)

    assert first == second


def test_resolve_path_uses_default_or_repo_relative(state_rebuilder, repo_context):
    default = repo_context.tx_event_log

    assert state_rebuilder.resolve_path(None, default) == default
    assert (
        state_rebuilder.resolve_path("logs/events.jsonl", default)
        == repo_context.get_repo_root() / "logs/events.jsonl"
    )
