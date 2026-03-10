import json
from pathlib import Path
from typing import Any, Dict

import pytest

from agentops_mcp_server.ops_tools import (
    OpsTools,
    build_compact_context,
    summarize_result,
    truncate_text,
)


class DummyGitRepo:
    def __init__(self, diff_value: str = "diff", diff_error: Exception | None = None):
        self.diff_value = diff_value
        self.diff_error = diff_error

    def diff_stat(self) -> str:
        if self.diff_error is not None:
            raise self.diff_error
        return self.diff_value


def _build_ops_tools(
    repo_context, state_store, state_rebuilder, git_repo: DummyGitRepo | None = None
):
    return OpsTools(
        repo_context, state_store, state_rebuilder, git_repo or DummyGitRepo()
    )


def _read_tx_events(repo_context):
    if not repo_context.tx_event_log.exists():
        return []
    return [
        json.loads(line)
        for line in repo_context.tx_event_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tx_event_types(repo_context):
    return [event["event_type"] for event in _read_tx_events(repo_context)]


def _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1", title="Build"):
    state_store.repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    state_store.repo_context.tx_event_log.write_text("", encoding="utf-8")
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    ticket_id = f"t-{tx_id}" if isinstance(tx_id, int) else str(tx_id)
    state_store.tx_event_append_and_state_save(
        tx_id=tx_id,
        ticket_id=ticket_id,
        event_type="tx.begin",
        phase="in-progress",
        step_id="none",
        actor={"tool": "test"},
        session_id=session_id,
        payload={"ticket_id": ticket_id, "ticket_title": title},
        state=rebuild["state"],
    )


def _set_active_tx(
    repo_context,
    *,
    tx_id: int = 1,
    ticket_id: str = "t-1",
    status: str = "in-progress",
    phase: str = "in-progress",
    current_step: str = "task",
    session_id: str = "s1",
) -> Dict[str, Any]:
    tx_state = {
        "schema_version": "0.4.0",
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": phase,
            "current_step": current_step,
            "last_completed_step": "",
            "next_action": "tx.verify.start",
            "semantic_summary": f"Entered step {current_step}",
            "user_intent": None,
            "session_id": session_id,
            "verify_state": {
                "status": "not_started",
                "last_result": None,
            },
            "commit_state": {
                "status": "not_started",
                "last_result": None,
            },
            "file_intents": [],
            "_last_event_seq": -1,
            "_terminal": False,
        },
        "last_applied_seq": 0,
        "integrity": {
            "state_hash": "test-hash",
            "rebuilt_from_seq": 0,
            "drift_detected": False,
            "active_tx_source": "materialized",
        },
        "updated_at": "2026-03-08T00:00:00+00:00",
    }
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return tx_state


def _assert_workflow_guidance_fields(result, *, expected_status, expected_phase):
    assert result["ok"] is True
    assert result["canonical_status"] == expected_status
    assert result["canonical_phase"] == expected_phase
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
    assert "active_tx" in result
    assert isinstance(result["active_tx"], dict)


def test_ops_compact_context_updates_journal(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_compact_context(max_chars=80, include_diff=False)

    assert result["ok"] is True
    assert isinstance(result["compact_context"], str)


def test_ops_compact_context_defaults_and_includes_diff(
    repo_context, state_store, state_rebuilder
):
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
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
    assert "current_task: t-1" in result["compact_context"]
    assert "diff_stat:" in result["compact_context"]
    assert "1 file changed" in result["compact_context"]


def test_ops_compact_context_uses_empty_values_when_states_missing(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = "bad"
    tx_state["active_tx"]["commit_state"] = None
    tx_state["active_tx"]["next_action"] = ""
    tx_state["active_tx"]["semantic_summary"] = ""
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=120, include_diff=False)

    assert result["ok"] is True
    assert "current_phase: in-progress" in result["compact_context"]
    assert "current_task: t-1" in result["compact_context"]


def test_ops_compact_context_truncates_without_diff(
    repo_context, state_store, state_rebuilder
):
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=20, include_diff=False)

    assert result["ok"] is True
    assert result["max_chars"] == 20
    assert result["compact_context"].endswith("...(truncated)")


def test_ops_handoff_export_materializes_rebuilt_next_action_when_missing(
    repo_context, state_store, state_rebuilder
):
    class RebuilderWithMissingNextAction:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "",
                        "semantic_summary": "Resume work.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "running",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 3,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 3,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, RebuilderWithMissingNextAction())

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["next_step"] == "resume-step"
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["next_action"] == "resume-step"


def test_ops_handoff_export_writes_json(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["wrote"] is True
    assert result["path"]

    handoff_payload = json.loads(repo_context.handoff.read_text(encoding="utf-8"))
    assert "compact_context" in handoff_payload


def test_ops_handoff_export_does_not_materialize_drifted_rebuild(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "in-progress",
                        "phase": "in-progress",
                        "current_step": "task",
                        "last_completed_step": "",
                        "next_action": "tx.verify.start",
                        "semantic_summary": "Drifted rebuild should not be materialized.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    _set_active_tx(
        repo_context,
        tx_id="materialized-tx",
        ticket_id="materialized-tx",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    before = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    handoff = result["handoff"]
    assert handoff["current_task"] == "materialized-tx"
    assert handoff["last_action"] == "Entered step resume-step"
    assert handoff["next_step"] == "tx.verify.start"

    after = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert after == before


def test_ops_handoff_export_defaults_to_safe_begin_when_only_drifted_rebuild_exists(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": "tx-drift",
                        "ticket_id": "p3-t04",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "p3-t04",
                        "last_completed_step": "",
                        "next_action": "tx.commit.start",
                        "semantic_summary": "Drifted rebuild should not drive handoff.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "passed",
                            "last_result": {"ok": True},
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 2,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 2,
                        "drift_detected": True,
                        "active_tx_source": "active_candidate",
                    },
                    "rebuild_warning": "duplicate tx.begin",
                    "rebuild_invalid_seq": 1,
                    "rebuild_observed_mismatch": {
                        "drift_reason": "duplicate tx.begin",
                        "last_applied_seq": 1,
                        "active_tx_id": "none",
                        "active_ticket_id": "none",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    repo_context.tx_state.unlink(missing_ok=True)
    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    handoff = result["handoff"]
    assert handoff["current_task"] == ""
    assert handoff["last_action"] == ""
    assert handoff["next_step"] == "tx.begin"
    assert handoff["compact_context"] == ""

    assert repo_context.tx_state.exists() is False


def test_ops_start_task_bootstraps_tx_on_zero_event_baseline(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    assert result["canonical_status"] == "in-progress"
    assert result["canonical_phase"] == "in-progress"
    assert result["tx_status"] == "in-progress"
    assert result["tx_phase"] == "in-progress"
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False

    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[0]["phase"] == "in-progress"
    assert events[1]["phase"] == "in-progress"


def test_ops_start_task_separates_opaque_tx_id_from_user_task_label(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(
        title="Build",
        task_id="v0.6.0/p2-t07",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[0]["ticket_id"] == "v0.6.0/p2-t07"
    assert events[1]["ticket_id"] == "v0.6.0/p2-t07"
    assert events[0]["payload"]["ticket_id"] == "v0.6.0/p2-t07"
    assert isinstance(events[0]["tx_id"], int)
    assert events[0]["tx_id"] > 0
    assert events[1]["tx_id"] == events[0]["tx_id"]
    assert events[0]["tx_id"] != events[0]["ticket_id"]


def test_ops_start_task_collision_across_releases_requires_resume_of_active_transaction(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(
        state_store,
        state_rebuilder,
        tx_id=1,
        session_id="s1",
        title="0.5.3 p2-t01",
    )

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=p2-t01, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="0.6.0 p2-t01", task_id="p2-t01", session_id="s2")


def test_ops_start_task_allows_distinct_release_scoped_ticket_labels_after_terminal_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(
        state_store,
        state_rebuilder,
        tx_id=1,
        session_id="s1",
        title="0.5.3 p2-t01",
    )
    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="v0.5.3/p2-t01",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )

    result = ops.ops_start_task(
        title="0.6.0 p2-t01",
        task_id="v0.6.0/p2-t01",
        session_id="s2",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-2]["event_type"] == "tx.begin"
    assert isinstance(events[-2]["tx_id"], int)
    assert events[-2]["tx_id"] > 0
    assert events[-2]["ticket_id"] == "v0.6.0/p2-t01"
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["tx_id"] == events[-2]["tx_id"]
    assert events[-1]["ticket_id"] == "v0.6.0/p2-t01"
    assert result["active_tx_id"] == events[-2]["tx_id"]
    assert result["active_ticket_id"] == "v0.6.0/p2-t01"
    assert result["current_step"] == "v0.6.0/p2-t01"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    event_types = [event["event_type"] for event in events]
    assert event_types[-2:] == ["tx.begin", "tx.step.enter"]
    assert events[-2]["payload"]["ticket_id"] == "v0.6.0/p2-t01"
    assert events[-2]["payload"]["ticket_title"] == "0.6.0 p2-t01"
    assert events[-1]["payload"]["step_id"] == "v0.6.0/p2-t01"
    assert events[-1]["payload"]["description"] == "task started"


def test_ops_start_task_requires_task_id_for_bootstrap(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="task_id is required to bootstrap tx.begin"):
        ops.ops_start_task(title="Build", session_id="s1")


def test_ops_start_task_ignores_non_in_progress_requested_status_for_phase(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(
        title="Build", task_id="t-1", session_id="s1", status="checking"
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[0]["phase"] == "in-progress"
    assert events[1]["phase"] == "in-progress"
    assert result["payload"]["requested_status"] == "checking"


def test_ops_start_task_allows_stringified_tx_id_for_exact_active_transaction_resume(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=12, session_id="s1")

    result = ops.ops_start_task(title="Build", task_id="12", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[-1]["tx_id"] == 12
    assert events[-1]["ticket_id"] == "t-12"


def test_ops_start_task_does_not_reverse_map_prefixed_string_to_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=12, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=tx-12, active_ticket=t-12, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="tx-12", session_id="s1")


def test_ops_start_task_does_not_treat_substring_like_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1207, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=207, active_ticket=t-1207, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="207", session_id="s1")


def test_ops_start_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=t-2, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=t-2, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_records_step_after_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    event_types = [event["event_type"] for event in events]
    assert event_types == ["tx.begin", "tx.step.enter"]
    step_event = events[-1]
    assert step_event["tx_id"] == 1
    assert step_event["session_id"] == "s1"
    assert step_event["payload"]["step_id"] == "t-1"
    assert step_event["payload"]["description"] == "task started"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


def test_ops_start_task_uses_existing_active_transaction_without_new_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[-1]["tx_id"] == 1
    assert events[-1]["ticket_id"] == "t-1"


def test_ops_start_task_treats_none_tx_id_as_bootstrap_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]


def test_ops_start_task_none_tx_id_still_requires_matching_active_context(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )

    result = ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[0]["ticket_id"] == "t-2"


def test_ops_update_task_uses_ticket_id_when_task_id_is_omitted(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_update_task(status="checking", note="step", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    update_events = [
        event for event in events if event["event_type"] == "tx.step.enter"
    ]
    assert update_events[-1]["ticket_id"] == "t-1"
    assert update_events[-1]["phase"] == "checking"


def test_ops_update_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_update_task(status="checking", note="step", session_id="s1")


def test_ops_update_task_recovers_session_id_from_tx_event_log_after_debug_start_time(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    repo_context.tx_state.write_text(
        json.dumps(
            {
                **json.loads(repo_context.tx_state.read_text(encoding="utf-8")),
                "active_tx": {
                    **json.loads(repo_context.tx_state.read_text(encoding="utf-8"))[
                        "active_tx"
                    ],
                    "session_id": "",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    repo_context.handoff.write_text(
        json.dumps(
            {
                "ts": "2026-03-09T08:31:00+00:00",
                "session_id": "ignored-before-debug",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_context.get_repo_root() / ".agent" / "debug_start_time.json").write_text(
        json.dumps(
            {"debug_start_time": "2026-03-09T08:32:52.363705+00:00"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state_store.append_json_line(
        repo_context.tx_event_log,
        {
            "seq": 2,
            "ts": "2026-03-09T08:33:10+00:00",
            "tx_id": 1,
            "ticket_id": "t-1",
            "event_type": "tx.step.enter",
            "phase": "checking",
            "step_id": "resume-step",
            "actor": {"tool": "test"},
            "session_id": "recovered-session",
            "payload": {"step_id": "resume-step", "description": "resume"},
        },
    )

    with pytest.raises(
        ValueError,
        match=(
            "cannot emit tx.begin for an already-active non-terminal transaction; "
            "resume it with task update semantics instead"
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-1",
            session_id="",
        )


def test_ops_update_task_requires_session_id_when_recovery_is_ambiguous(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["session_id"] = ""
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (repo_context.get_repo_root() / ".agent" / "debug_start_time.json").write_text(
        json.dumps(
            {"debug_start_time": "2026-03-09T08:32:52.363705+00:00"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state_store.append_json_line(
        repo_context.tx_event_log,
        {
            "seq": 2,
            "ts": "2026-03-09T08:33:10+00:00",
            "tx_id": 1,
            "ticket_id": "t-1",
            "event_type": "tx.step.enter",
            "phase": "checking",
            "step_id": "resume-step",
            "actor": {"tool": "test"},
            "session_id": "recovered-session-1",
            "payload": {"step_id": "resume-step", "description": "resume"},
        },
    )
    state_store.append_json_line(
        repo_context.tx_event_log,
        {
            "seq": 3,
            "ts": "2026-03-09T08:33:11+00:00",
            "tx_id": 1,
            "ticket_id": "t-1",
            "event_type": "tx.user_intent.set",
            "phase": "checking",
            "step_id": "resume-step",
            "actor": {"tool": "test"},
            "session_id": "recovered-session-2",
            "payload": {"user_intent": "continue"},
        },
    )

    with pytest.raises(
        ValueError,
        match=(
            "cannot emit tx.begin for an already-active non-terminal transaction; "
            "resume it with task update semantics instead"
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-1",
            session_id="",
        )


def test_ops_update_task_falls_back_to_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_update_task(status="checking", note="waiting", session_id="s1")

    events = _read_tx_events(repo_context)
    update_events = [
        event
        for event in events
        if event["event_type"] == "tx.step.enter"
        and event.get("payload", {}).get("description") == "waiting"
    ]
    assert update_events
    assert update_events[-1]["tx_id"] == 1
    assert update_events[-1]["session_id"] == "s1"
    assert update_events[-1]["phase"] == "checking"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == 1
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["next_action"] == "tx.verify.start"

    assert result["ok"] is True
    assert result["canonical_status"] == "checking"
    assert result["canonical_phase"] == "checking"
    assert result["tx_status"] == "checking"
    assert result["tx_phase"] == "checking"
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"


def test_ops_update_task_allows_stringified_tx_id_for_exact_active_transaction(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=12, session_id="s1")

    result = ops.ops_update_task(
        status="checking",
        note="waiting",
        task_id="12",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["tx_id"] == 12
    assert events[-1]["ticket_id"] == "t-12"


def test_ops_update_task_rejects_prefixed_string_as_reverse_mapping_to_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=12, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=tx-12, active_ticket=t-12, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="waiting",
            task_id="tx-12",
            session_id="s1",
        )


def test_ops_update_task_prefers_materialized_state_over_rebuild(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = ops.ops_update_task(
        status="checking",
        note="step",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events == []

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "resume-step"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == 0


def test_ops_end_task_prefers_materialized_state_over_rebuild(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="committed",
        phase="committed",
        current_step="resume-step",
        session_id="s1",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = ops.ops_end_task(
        summary="done",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events == []

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "committed"
    assert active_tx["phase"] == "committed"
    assert active_tx["current_step"] == "resume-step"
    assert active_tx["session_id"] == "s1"
    assert active_tx["next_action"] == "tx.verify.start"
    assert tx_state["last_applied_seq"] == 0

    assert result["ok"] is True
    assert result["canonical_status"] == "committed"
    assert result["canonical_phase"] == "committed"
    assert result["tx_status"] == "committed"
    assert result["tx_phase"] == "committed"
    assert result["next_action"] == "tx.begin"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == "t-1"
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "resume-step"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True


def test_ops_update_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=t-2, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-2",
            session_id="s1",
        )


def test_ops_update_task_rejects_terminal_statuses(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(ValueError, match="use ops_end_task for terminal done state"):
        ops.ops_update_task(status="done", note="done", session_id="s1")

    with pytest.raises(ValueError, match="use ops_end_task for terminal blocked state"):
        ops.ops_update_task(status="blocked", note="blocked", session_id="s1")


def test_ops_end_task_requires_terminal_status_values(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(ValueError, match="ops_end_task status must be done or blocked"):
        ops.ops_end_task(
            summary="not terminal",
            status="checking",
            session_id="s1",
        )


def test_ops_compact_context_includes_last_error_and_last_commit(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="verified",
        phase="verified",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "failed",
        "last_result": {"error": "verify boom"},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"sha": "abc123", "summary": "commit summary"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=400, include_diff=False)

    assert result["ok"] is True
    assert "last_error: verify boom" in result["compact_context"]
    assert "last_commit: abc123" in result["compact_context"]


def test_ops_compact_context_uses_commit_error_when_verify_error_missing(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="verified",
        phase="verified",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "failed",
        "last_result": {"error": "commit boom"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=400, include_diff=False)

    assert result["ok"] is True
    assert "last_error: commit boom" in result["compact_context"]


def test_ops_update_task_rejects_unsupported_status(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(ValueError, match="unsupported status for ops_update_task"):
        ops.ops_update_task(status="planned", note="step", session_id="s1")


def test_ops_update_task_requires_status_or_note(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(ValueError, match="status or note is required"):
        ops.ops_update_task(session_id="s1")


def test_ops_end_task_emits_blocked_terminal_event(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_end_task(
        summary="blocked on dependency",
        next_action="wait",
        status="blocked",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "blocked"
    assert result["canonical_phase"] == "blocked"

    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.end.blocked"
    assert events[-1]["payload"]["summary"] == "blocked on dependency"
    assert events[-1]["payload"]["reason"] == "blocked on dependency"
    assert events[-1]["payload"]["next_action"] == "wait"


def test_ops_end_task_allows_done_when_phase_is_committed_even_without_commit_state_passed(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    tx_state = _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="committed",
        phase="committed",
        current_step="t-1",
        session_id="s1",
    )
    tx_state["active_tx"]["commit_state"] = {
        "status": "running",
        "last_result": None,
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = ops.ops_end_task(
        summary="complete",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.end.done"


def test_ops_end_task_allows_done_when_commit_has_passed(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    tx_state = _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="verified",
        phase="verified",
        current_step="t-1",
        session_id="s1",
    )
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"ok": True, "sha": "abc123"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = ops.ops_end_task(
        summary="complete",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True


def test_ops_update_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=t-2, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-2",
            session_id="s1",
        )


def test_ops_resume_brief_reports_active_transaction_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    ops.ops_update_task(
        status="checking",
        note="step",
        session_id="s1",
    )

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    brief = result["brief"]
    assert "- ticket_id: t-1" in brief
    assert "- status: checking" in brief
    assert "- next_action: tx.verify.start" in brief
    assert "- can_start_new_ticket: no" in brief


def test_ops_update_task_records_user_intent(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "cannot emit tx.begin for an already-active non-terminal transaction; "
            "resume it with task update semantics instead"
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-1",
            session_id="s1",
            user_intent="continue",
        )


def test_ops_end_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_end_task(summary="done", session_id="s1")


def test_ops_update_task_records_user_intent_when_task_id_is_omitted(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_update_task(
        status="checking",
        note="step",
        session_id="s1",
        user_intent="continue",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.step.enter",
        "tx.user_intent.set",
    ]
    assert events[-1]["payload"]["user_intent"] == "continue"


def test_ops_end_task_rejects_done_before_commit_finished(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "cannot mark task done before commit is finished; "
            "complete commit workflow first"
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-1", status="done", session_id="s1")


def test_ops_end_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, "
            "requested_task=t-2, active_ticket=t-1, status=in-progress, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-2", session_id="s1")


def test_ops_end_task_requires_session_id(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "cannot mark task done before commit is finished; "
            "complete commit workflow first"
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-1", session_id="")


def test_ops_end_task_emits_terminal_event_and_updates_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["status"] = "committed"
    tx_state["active_tx"]["phase"] = "committed"
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"sha": "abc123"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = ops.ops_end_task(
        summary="done",
        next_action="next",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    tx_events = _tx_event_types(repo_context)
    assert tx_events == ["tx.begin", "tx.step.enter", "tx.end.done"]

    events = _read_tx_events(repo_context)
    end_event = events[-1]
    assert end_event["session_id"] == "s1"
    assert end_event["payload"]["summary"] == "done"
    assert end_event["payload"]["next_action"] == "next"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    last_seq = max(event["seq"] for event in events)
    assert tx_state["last_applied_seq"] == last_seq
    assert tx_state["integrity"]["rebuilt_from_seq"] == last_seq
    assert result["canonical_status"] == "done"
    assert result["canonical_phase"] == "done"
    assert result["tx_status"] == "done"
    assert result["tx_phase"] == "done"
    assert result["next_action"] == "tx.begin"
    assert result["terminal"] is True
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "passed"
    assert result["can_start_new_ticket"] is True
    assert result["resume_required"] is False


def test_ops_end_task_uses_ticket_id_when_tx_id_is_none(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_end_task(summary="done", task_id="t-1", session_id="s1")


def test_ops_start_task_restarts_after_terminal_active_tx(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )

    result = ops.ops_start_task(title="Restart", task_id="t-2", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert isinstance(events[0]["tx_id"], int)
    assert events[0]["ticket_id"] == "t-2"
    assert isinstance(events[1]["tx_id"], int)
    assert events[1]["payload"]["step_id"] == "t-2"


def test_ops_start_task_terminal_active_tx_without_task_id_requires_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )

    with pytest.raises(ValueError, match="task_id is required to bootstrap tx.begin"):
        ops.ops_start_task(title="Restart", session_id="s1")


def test_ops_start_task_rejects_begin_when_materialized_state_is_missing_but_rebuild_has_active_tx(
    repo_context, state_store, state_rebuilder
):
    class ActiveRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "in-progress",
                        "phase": "in-progress",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "tx.verify.start",
                        "semantic_summary": "Entered step resume-step",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                        "_last_event_seq": 1,
                        "_terminal": False,
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, ActiveRebuilder())
    repo_context.tx_state.unlink(missing_ok=True)

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Restart", task_id="t-2", session_id="s1")

    assert _tx_event_types(repo_context) == []


def test_resolve_session_id_uses_explicit_value(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._resolve_session_id(" s1 ") == "s1"


def test_resolve_session_id_uses_materialized_session_without_recovery(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    active_tx = _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )["active_tx"]

    assert ops._resolve_session_id("", active_tx, allow_recovery=False) == "s1"


def test_resolve_session_id_raises_when_missing_and_recovery_disabled(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    active_tx = {
        "tx_id": 1,
        "ticket_id": "t-1",
        "status": "checking",
        "phase": "checking",
        "current_step": "resume-step",
        "session_id": "",
    }

    with pytest.raises(ValueError, match="session_id is required"):
        ops._resolve_session_id("", active_tx, allow_recovery=False)


def test_recover_session_id_returns_unique_candidate_from_agent_artifact(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.handoff.parent.mkdir(parents=True, exist_ok=True)
    repo_context.handoff.write_text(
        json.dumps(
            {"session_id": "handoff-session"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    recovered = ops._recover_session_id_from_agent_artifacts(
        {"tx_id": 1, "ticket_id": "t-1"}
    )

    assert recovered == "handoff-session"


def test_iter_candidate_session_ids_from_agent_artifact_reads_jsonl_after_debug_start_time(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "sessions.jsonl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "ts": "2026-03-09T08:31:00+00:00",
                        "session_id": "before-debug",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "ts": "2026-03-09T08:33:00+00:00",
                        "session_id": "after-debug-1",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "ts": "2026-03-09T08:33:10+00:00",
                        "nested": {"session_id": "after-debug-2"},
                    },
                    ensure_ascii=False,
                ),
                "{bad json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        ops._parse_iso_datetime("2026-03-09T08:32:52.363705+00:00"),
    )

    assert sessions == ["after-debug-1", "after-debug-2"]


def test_iter_candidate_session_ids_from_agent_artifact_ignores_old_json_payload(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "artifact.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "updated_at": "2026-03-09T08:31:00+00:00",
                "session_id": "too-old",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        ops._parse_iso_datetime("2026-03-09T08:32:52.363705+00:00"),
    )

    assert sessions == []


def test_iter_candidate_session_ids_from_agent_artifact_returns_empty_on_os_error(
    repo_context, state_store, state_rebuilder, monkeypatch
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "broken.jsonl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        None,
    )

    assert sessions == []


def test_recover_session_id_raises_when_fallback_candidates_are_ambiguous(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.handoff.parent.mkdir(parents=True, exist_ok=True)
    repo_context.handoff.write_text(
        json.dumps(
            {"session_id": "handoff-session-1"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    repo_context.observability.write_text(
        json.dumps(
            {"session_id": "handoff-session-2"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "session_id is required; unable to recover prior session_id from .agent "
            "artifacts after debug_start_time"
        ),
    ):
        ops._recover_session_id_from_agent_artifacts({"tx_id": 1, "ticket_id": "t-1"})


def test_recover_session_id_raises_when_matching_candidates_are_ambiguous(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "ts": "2026-03-09T08:33:10+00:00",
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "session_id": "session-a",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "ts": "2026-03-09T08:33:11+00:00",
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "session_id": "session-b",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=(
            "session_id is required; unable to recover a unique prior session_id "
            "from .agent artifacts after debug_start_time"
        ),
    ):
        ops._recover_session_id_from_agent_artifacts({"tx_id": 1, "ticket_id": "t-1"})


def test_iter_candidate_session_ids_from_agent_artifact_collects_list_entries(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "list-artifact.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "items": [
                    {"session_id": "list-session-1"},
                    {"nested": [{"session_id": "list-session-2"}]},
                    {"session_id": "list-session-1"},
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        None,
    )

    assert sessions == ["list-session-1", "list-session-2"]


def test_recover_session_id_matches_ticket_id_when_tx_id_is_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(
            {
                "seq": 1,
                "ts": "2026-03-09T08:33:10+00:00",
                "tx_id": "",
                "ticket_id": "t-1",
                "session_id": "ticket-match-session",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    recovered = ops._recover_session_id_from_agent_artifacts(
        {"tx_id": "", "ticket_id": "t-1"}
    )

    assert recovered == "ticket-match-session"


def test_canonical_begin_conflict_returns_none_when_requested_task_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._canonical_begin_conflict(None) is None


def test_iter_candidate_session_ids_from_agent_artifact_returns_empty_for_missing_file(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "missing.json"

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        None,
    )

    assert sessions == []


def test_iter_candidate_session_ids_from_agent_artifact_returns_empty_for_non_file_path(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_dir = repo_context.handoff.parent / "artifact-dir"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_dir,
        None,
    )

    assert sessions == []


def test_iter_candidate_session_ids_from_agent_artifact_returns_empty_for_non_dict_json(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "list-only.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(["not", "a", "dict"], ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        None,
    )

    assert sessions == []


def test_iter_candidate_session_ids_from_agent_artifact_accepts_json_without_timestamp_after_debug_start_time(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "missing-ts.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "session_id": "no-ts-session",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        ops._parse_iso_datetime("2026-03-09T08:32:52.363705+00:00"),
    )

    assert sessions == ["no-ts-session"]


def test_extract_last_commit_prefers_summary_when_sha_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    commit = ops._extract_last_commit(
        {
            "last_result": {
                "summary": "commit summary only",
            }
        }
    )

    assert commit == "commit summary only"


def test_extract_last_commit_returns_empty_for_non_dict_last_result(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    commit = ops._extract_last_commit({"last_result": "bad"})

    assert commit == ""


def test_extract_last_error_returns_empty_for_non_dict_last_result(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    error = ops._extract_last_error({"last_result": "bad"}, None)

    assert error == ""


def test_canonical_begin_conflict_rejects_matching_materialized_ticket_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    conflict = ops._canonical_begin_conflict("t-1")

    assert isinstance(conflict, ValueError)
    assert str(conflict) == (
        "cannot emit tx.begin for an already-active non-terminal transaction; "
        "resume it with task update semantics instead"
    )


def test_canonical_begin_conflict_does_not_reverse_map_materialized_tx_string_shapes(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id="ticket-x",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    conflict = ops._canonical_begin_conflict("123")

    assert conflict is None


def test_emit_tx_event_uses_rebuild_state_when_materialized_state_is_not_dict(
    repo_context, state_store, state_rebuilder
):
    repo_context.tx_state.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_state.write_text("[]\n", encoding="utf-8")
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "from rebuild"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id=None,
    )

    assert result is not None
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"

    saved_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved_state["active_tx"]["tx_id"] == 1
    assert saved_state["active_tx"]["ticket_id"] == "t-1"
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "resume-step"
    assert saved_state["active_tx"]["session_id"] == "s1"


def test_emit_tx_event_uses_rebuild_state_when_rebuild_active_tx_is_not_dict(
    repo_context, state_store, state_rebuilder
):
    class NonDictActiveRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": [],
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, NonDictActiveRebuilder())

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "from rebuild list"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id=None,
    )

    assert result is not None
    saved_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved_state["active_tx"]["tx_id"] == 1
    assert saved_state["active_tx"]["ticket_id"] == "t-1"
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["phase"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "resume-step"
    assert saved_state["active_tx"]["session_id"] == "s1"


def test_canonical_begin_conflict_returns_drift_error_when_rebuild_detects_integrity_issue(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                    },
                    "integrity": {
                        "drift_detected": True,
                    },
                },
            }

    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())

    conflict = ops._canonical_begin_conflict("t-2")

    assert isinstance(conflict, ValueError)
    assert "canonical transaction history has integrity drift" in str(conflict)


def test_canonical_begin_conflict_rejects_matching_rebuilt_ticket_before_terminal_materialized_branch(
    repo_context, state_store, state_rebuilder
):
    class ActiveRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "active_tx": {
                        "tx_id": "tx-123",
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "next_action": "tx.verify.start",
                    },
                    "integrity": {
                        "drift_detected": False,
                    },
                },
            }

    _set_active_tx(
        repo_context,
        tx_id="tx-9",
        ticket_id="t-9",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, ActiveRebuilder())

    conflict = ops._canonical_begin_conflict("t-1")

    assert isinstance(conflict, ValueError)
    assert str(conflict) == (
        "cannot emit tx.begin for an already-active non-terminal transaction; "
        "resume it with task update semantics instead"
    )


def test_canonical_begin_conflict_returns_none_for_terminal_materialized_state_with_unrelated_rebuilt_tx(
    repo_context, state_store, state_rebuilder
):
    class ActiveRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "active_tx": {
                        "tx_id": "tx-123",
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                    },
                    "integrity": {
                        "drift_detected": False,
                    },
                },
            }

    _set_active_tx(
        repo_context,
        tx_id="tx-9",
        ticket_id="t-9",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, ActiveRebuilder())

    assert ops._canonical_begin_conflict("other-ticket") is None


def test_resolve_session_id_uses_recovered_active_tx_when_active_tx_argument_is_not_dict(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(
            {
                "seq": 1,
                "ts": "2026-03-09T08:33:10+00:00",
                "tx_id": 1,
                "ticket_id": "t-1",
                "session_id": "recovered-session",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    assert ops._resolve_session_id("", [], allow_recovery=True) == "recovered-session"


def test_recover_session_id_ignores_non_matching_event_log_records_and_uses_fallback_artifact(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "seq": 1,
                        "ts": "2026-03-09T08:33:10+00:00",
                        "tx_id": 99,
                        "ticket_id": "other-ticket",
                        "session_id": "other-session",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "seq": 2,
                        "ts": "2026-03-09T08:33:11+00:00",
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "session_id": " ",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repo_context.handoff.write_text(
        json.dumps(
            {"session_id": "fallback-session"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    recovered = ops._recover_session_id_from_agent_artifacts(
        {"tx_id": 1, "ticket_id": "t-1"}
    )

    assert recovered == "fallback-session"


def test_iter_candidate_session_ids_from_agent_artifact_ignores_jsonl_records_without_parseable_timestamp_after_debug_start_time(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    artifact_path = repo_context.handoff.parent / "invalid-ts.jsonl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "ts": "not-a-timestamp",
                "session_id": "ignored-session",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = ops._iter_candidate_session_ids_from_agent_artifact(
        artifact_path,
        ops._parse_iso_datetime("2026-03-09T08:32:52.363705+00:00"),
    )

    assert sessions == []


def test_ops_start_task_uses_requested_status_payload_without_changing_begin_phase(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(
        title="Build",
        task_id="t-1",
        session_id="s1",
        status="verified",
    )

    assert result["ok"] is True
    assert result["payload"]["requested_status"] == "verified"
    events = _read_tx_events(repo_context)
    assert events[0]["event_type"] == "tx.begin"
    assert events[0]["phase"] == "in-progress"
    assert events[1]["event_type"] == "tx.step.enter"
    assert events[1]["phase"] == "in-progress"


def test_ops_observability_summary_includes_timestamp_in_recent_event_lines(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_observability_summary(session_id="s1", max_events=5, max_chars=400)

    assert result["ok"] is True
    assert "- 1 tx.begin @" in result["text"]
    assert "- 2 tx.step.enter @" in result["text"]


def test_workflow_success_response_backfills_guidance_when_success_response_is_empty(
    repo_context, state_store, state_rebuilder, monkeypatch
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    monkeypatch.setattr(
        "agentops_mcp_server.ops_tools.build_success_response",
        lambda **kwargs: {"ok": True},
    )

    result = ops._workflow_success_response(payload={"note": "x"})

    assert result["ok"] is True
    assert result["canonical_status"] == "checking"
    assert result["canonical_phase"] == "checking"
    assert "next_action" in result
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "resume-step"


def test_workflow_success_response_uses_empty_state_defaults_when_tx_state_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops._workflow_success_response(tx_state=[])

    assert result["ok"] is True
    assert result["active_tx"] == {}
    assert result["active_tx_id"] is None
    assert result["active_ticket_id"] is None
    assert result["current_step"] is None
    assert result["verify_status"] is None
    assert result["commit_status"] is None
    assert result["integrity_status"] == "healthy"


def test_workflow_success_response_marks_integrity_blocked_when_tx_state_drifts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops._workflow_success_response(
        tx_state={
            "active_tx": {
                "tx_id": 1,
                "ticket_id": "t-1",
                "current_step": "resume-step",
                "verify_state": {"status": "passed"},
                "commit_state": {"status": "committed"},
            },
            "integrity": {"drift_detected": True},
        }
    )

    assert result["ok"] is True
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "resume-step"
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "committed"
    assert result["integrity_status"] == "blocked"


def test_normalize_tx_identifier_handles_edge_values(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._normalize_tx_identifier(True) == ""
    assert ops._normalize_tx_identifier(42) == "42"
    assert ops._normalize_tx_identifier("  none  ") == ""
    assert ops._normalize_tx_identifier("  tx-9  ") == "tx-9"
    assert ops._normalize_tx_identifier([]) == ""


def test_is_terminal_active_tx_accepts_status_phase_and_terminal_flag(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._is_terminal_active_tx({"status": "done"}) is True
    assert ops._is_terminal_active_tx({"phase": "blocked"}) is True
    assert ops._is_terminal_active_tx({"_terminal": True}) is True
    assert (
        ops._is_terminal_active_tx({"status": "checking", "phase": "checking"}) is False
    )


def test_require_active_tx_rejects_missing_begin_for_ticket_only_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops._require_active_tx("t-1")


def test_require_active_tx_allows_resume_for_matching_ticket_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    active_tx, canonical_id = ops._require_active_tx("t-1", allow_resume=True)

    assert active_tx["ticket_id"] == "t-1"
    assert canonical_id == "tx-123"


def test_ops_start_task_rejects_begin_when_materialized_terminal_state_conflicts_with_rebuilt_active_tx(
    repo_context, state_store, state_rebuilder
):
    class ActiveRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "in-progress",
                        "phase": "in-progress",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "tx.verify.start",
                        "semantic_summary": "Entered step resume-step",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                        "_last_event_seq": 2,
                        "_terminal": False,
                    },
                    "last_applied_seq": 2,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 2,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, ActiveRebuilder())
    _set_active_tx(
        repo_context,
        tx_id="t-9",
        ticket_id="t-9",
        status="done",
        phase="done",
        current_step="complete",
        session_id="s1",
    )

    result = ops.ops_start_task(title="Restart", task_id="t-2", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert isinstance(events[0]["tx_id"], int)
    assert events[0]["ticket_id"] == "t-2"
    assert isinstance(events[1]["tx_id"], int)
    assert events[1]["payload"]["step_id"] == "t-2"


def test_ops_add_file_intent_emits_add_event_and_updates_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = result["active_tx_id"]

    result = ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "in-progress"
    assert result["canonical_phase"] == "in-progress"
    assert result["tx_status"] == "in-progress"
    assert result["tx_phase"] == "in-progress"
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == active_tx_id
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == [
        "tx.begin",
        "tx.step.enter",
        "tx.file_intent.add",
    ]
    add_event = events[-1]
    assert add_event["payload"]["path"] == "src/file.py"
    assert add_event["payload"]["operation"] == "update"
    assert add_event["payload"]["purpose"] == "implement helper"
    assert add_event["payload"]["planned_step"] == "t-1"
    assert add_event["payload"]["state"] == "planned"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    intents = tx_state["active_tx"]["file_intents"]
    assert intents == [
        {
            "path": "src/file.py",
            "operation": "update",
            "purpose": "implement helper",
            "planned_step": "t-1",
            "state": "planned",
            "last_event_seq": add_event["seq"],
        }
    ]


def test_ops_add_file_intent_requires_current_step(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step=" ",
        session_id="s1",
    )

    with pytest.raises(
        ValueError, match="current_step is required before adding file intent"
    ):
        ops.ops_add_file_intent(
            path="src/file.py",
            operation="update",
            purpose="implement helper",
            task_id="t-1",
            session_id="s1",
        )


def test_ops_update_file_intent_emits_update_event_and_advances_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]
    ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    result = ops.ops_update_file_intent(
        path="src/file.py",
        state="applied",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "in-progress"
    assert result["canonical_phase"] == "in-progress"
    assert result["tx_status"] == "in-progress"
    assert result["tx_phase"] == "in-progress"
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == active_tx_id
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["verify_status"] == "not_started"
    assert result["commit_status"] == "not_started"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.file_intent.update"
    assert events[-1]["payload"]["path"] == "src/file.py"
    assert events[-1]["payload"]["state"] == "applied"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    intents = tx_state["active_tx"]["file_intents"]
    assert intents[0]["state"] == "applied"
    assert intents[0]["last_event_seq"] == events[-1]["seq"]


def test_ops_update_file_intent_rejects_update_before_register(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]

    with pytest.raises(ValueError, match="file intent missing for path"):
        ops.ops_update_file_intent(
            path="src/file.py",
            state="applied",
            task_id=str(active_tx_id),
            session_id="s1",
        )


def test_ops_update_file_intent_recovers_session_id_from_errors_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]
    ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["session_id"] = ""
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (repo_context.get_repo_root() / ".agent" / "debug_start_time.json").write_text(
        json.dumps(
            {"debug_start_time": "2026-03-09T08:32:52.363705+00:00"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state_store.append_json_line(
        repo_context.errors,
        {
            "ts": "2026-03-09T08:33:20+00:00",
            "tool_name": "ops_update_task",
            "tool_input": {"task_id": "t-1"},
            "tool_output": {"error": "session_id is required"},
            "diagnostics": {
                "session_context": {
                    "requested_session_id": "",
                    "active_session_id": "recovered-from-errors",
                }
            },
        },
    )

    result = ops.ops_update_file_intent(
        path="src/file.py",
        state="applied",
        task_id=str(active_tx_id),
        session_id="",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.file_intent.update"
    assert events[-1]["session_id"] == "s1"


def test_ops_update_file_intent_rejects_verified_before_verify_pass(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]
    ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )
    ops.ops_update_file_intent(
        path="src/file.py",
        state="applied",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    with pytest.raises(ValueError, match="file intent verified requires verify.pass"):
        ops.ops_update_file_intent(
            path="src/file.py",
            state="verified",
            task_id=str(active_tx_id),
            session_id="s1",
        )


def test_ops_complete_file_intent_emits_complete_after_verify_pass(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]
    ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )
    ops.ops_update_file_intent(
        path="src/file.py",
        state="applied",
        task_id=str(active_tx_id),
        session_id="s1",
    )
    state_store.tx_event_append(
        tx_id=active_tx_id,
        ticket_id="t-1",
        event_type="tx.verify.start",
        phase="checking",
        step_id="t-1",
        actor={"tool": "test"},
        session_id="s1",
        payload={},
    )
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["verify_state"] = {
        "status": "running",
        "last_result": None,
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state_store.tx_event_append(
        tx_id=active_tx_id,
        ticket_id="t-1",
        event_type="tx.verify.pass",
        phase="verified",
        step_id="t-1",
        actor={"tool": "test"},
        session_id="s1",
        payload={"ok": True},
    )
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = ops.ops_complete_file_intent(
        path="src/file.py",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "in-progress"
    assert result["canonical_phase"] == "in-progress"
    assert result["tx_status"] == "in-progress"
    assert result["tx_phase"] == "in-progress"
    assert result["next_action"] == "tx.verify.start"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["active_tx_id"] == active_tx_id
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "not_started"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.file_intent.complete"
    assert events[-1]["payload"]["path"] == "src/file.py"
    assert events[-1]["payload"]["state"] == "verified"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    intents = tx_state["active_tx"]["file_intents"]
    assert intents[0]["state"] == "verified"
    assert intents[0]["last_event_seq"] == events[-1]["seq"]


def test_ops_complete_file_intent_rejects_before_verify_pass(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    active_tx_id = start_result["active_tx_id"]
    ops.ops_add_file_intent(
        path="src/file.py",
        operation="update",
        purpose="implement helper",
        task_id=str(active_tx_id),
        session_id="s1",
    )
    ops.ops_update_file_intent(
        path="src/file.py",
        state="applied",
        task_id=str(active_tx_id),
        session_id="s1",
    )

    with pytest.raises(ValueError, match="file intent verified requires verify.pass"):
        ops.ops_complete_file_intent(
            path="src/file.py",
            task_id=str(active_tx_id),
            session_id="s1",
        )


def test_ops_complete_file_intent_requires_current_step(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step=" ",
        session_id="s1",
    )

    with pytest.raises(
        ValueError, match="current_step is required before completing file intent"
    ):
        ops.ops_complete_file_intent(
            path="src/file.py",
            task_id="t-1",
            session_id="s1",
        )


def test_ops_end_task_rejects_mismatch_against_active_ticket_id_when_tx_id_is_none(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, requested_task=t-2, "
            "active_ticket=t-1, status=checking, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-2", session_id="s1")


def test_ops_capture_state_success_exposes_workflow_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="verify-step",
        session_id="s1",
    )

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["reason"] == "tx_event_log missing"


def test_ops_capture_state_returns_success_when_rebuild_is_ok_without_event_log_fixture(
    repo_context, state_store, monkeypatch
):
    class CaptureRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "",
                        "semantic_summary": "Resume work.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "running",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 4,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 4,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, CaptureRebuilder())
    monkeypatch.setattr(
        ops,
        "_workflow_success_response",
        lambda **kwargs: {
            "ok": True,
            "canonical_status": "checking",
            "canonical_phase": "checking",
            "next_action": "resume-step",
            "requires_followup": True,
            "followup_tool": None,
            "can_start_new_ticket": False,
            "resume_required": True,
        },
    )

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    assert result["state"]["ok"] is True
    assert result["last_applied_seq"] == 4
    assert result["integrity_status"] == "ok"
    assert result["next_action"] == "resume-step"
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["next_action"] == "resume-step"


def test_ops_capture_state_preserves_existing_next_action_when_present(
    repo_context, state_store, monkeypatch
):
    class CaptureRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "tx.commit.start",
                        "semantic_summary": "Resume work.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "running",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 5,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 5,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, CaptureRebuilder())
    monkeypatch.setattr(
        ops,
        "_workflow_success_response",
        lambda **kwargs: {
            "ok": True,
            "canonical_status": "checking",
            "canonical_phase": "checking",
            "next_action": "tx.commit.start",
            "requires_followup": True,
            "followup_tool": None,
            "can_start_new_ticket": False,
            "resume_required": True,
        },
    )

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["next_action"] == "tx.commit.start"
    assert result["next_action"] == "tx.commit.start"


def test_ops_task_summary_emits_journal(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_id"] == "t-1"
    assert len(result["text"]) <= 40


def test_ops_observability_summary_includes_artifacts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    start_result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    ops.ops_end_task(
        summary="waiting",
        status="blocked",
        task_id=str(start_result["active_tx_id"]),
        session_id="s1",
    )

    result = ops.ops_observability_summary(session_id="s1", max_events=5, max_chars=200)
    assert result["ok"] is True
    summary = result["summary"]
    assert summary["recent_events"]
    assert any(
        event.get("event_type") == "tx.begin" for event in summary["recent_events"]
    )

    assert repo_context.observability.exists()
    text_path = repo_context.observability.with_suffix(".txt")
    assert text_path.exists()


def test_ops_resume_brief_is_bounded(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_resume_brief(max_chars=20)
    assert result["ok"] is True
    assert len(result["brief"]) <= 20


def test_ops_capture_state_updates_tx_state(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_capture_state(session_id="s1")
    assert result["ok"] is True

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    events = _read_tx_events(repo_context)
    last_seq = max(event["seq"] for event in events)
    assert tx_state["last_applied_seq"] == last_seq


def test_ops_capture_state_fills_next_action_from_current_step(
    repo_context, state_store, state_rebuilder
):
    class CaptureRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "",
                        "semantic_summary": "Resume work.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "running",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 4,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 4,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, CaptureRebuilder())

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["next_action"] == "resume-step"


def test_ops_capture_state_preserves_literal_none_current_step(
    repo_context, state_store, state_rebuilder
):
    class CaptureRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 0,
                        "ticket_id": "none",
                        "status": "planned",
                        "phase": "planned",
                        "current_step": "none",
                        "last_completed_step": "",
                        "next_action": "",
                        "semantic_summary": "No active transaction.",
                        "user_intent": None,
                        "session_id": "",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 0,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 0,
                        "drift_detected": False,
                        "active_tx_source": "none",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, CaptureRebuilder())

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is True
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert tx_state["active_tx"]["next_action"] == "none"


def test_ops_capture_state_returns_error_without_canonical_event_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["reason"] == "tx_event_log missing"


def test_load_tx_state_ignores_rebuild_when_integrity_drift_detected(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "in-progress",
                        "phase": "in-progress",
                        "current_step": "task",
                        "last_completed_step": "",
                        "next_action": "tx.verify.start",
                        "semantic_summary": "Rebuilt state from tx event log.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())
    repo_context.tx_state.unlink(missing_ok=True)

    assert ops._load_tx_state() == {}


def test_ops_capture_state_refuses_rebuild_with_integrity_drift(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 0,
                        "ticket_id": "none",
                        "status": "planned",
                        "phase": "planned",
                        "current_step": "none",
                        "last_completed_step": "",
                        "next_action": "tx.begin",
                        "semantic_summary": "No active transaction.",
                        "user_intent": None,
                        "session_id": "",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "none",
                    },
                    "rebuild_warning": "duplicate tx.begin",
                    "rebuild_invalid_seq": 1,
                    "rebuild_observed_mismatch": {
                        "drift_reason": "duplicate tx.begin",
                        "last_applied_seq": 1,
                        "active_tx_id": "none",
                        "active_ticket_id": "none",
                        "invalid_reason": "duplicate tx.begin",
                        "invalid_event": {
                            "seq": 2,
                            "event_type": "tx.begin",
                            "tx_id": 1,
                            "ticket_id": "t-1",
                        },
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())
    repo_context.tx_state.unlink(missing_ok=True)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["reason"] == "rebuild integrity drift detected"
    assert result["integrity"]["drift_detected"] is True
    assert result["rebuild_warning"] == "duplicate tx.begin"
    assert result["rebuild_invalid_seq"] == 1
    assert result["rebuild_observed_mismatch"]["drift_reason"] == "duplicate tx.begin"
    assert (
        result["rebuild_observed_mismatch"]["invalid_event"]["event_type"] == "tx.begin"
    )
    assert result["active_tx"]["tx_id"] == 0
    assert result["active_tx"]["ticket_id"] == "none"
    assert result["active_tx"]["next_action"] == "tx.begin"


def test_ops_capture_state_returns_actionable_guidance_for_duplicate_begin_drift(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 0,
                        "ticket_id": "none",
                        "status": "planned",
                        "phase": "planned",
                        "current_step": "none",
                        "last_completed_step": "",
                        "next_action": "tx.begin",
                        "semantic_summary": "No active transaction.",
                        "user_intent": None,
                        "session_id": "",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "none",
                    },
                    "rebuild_warning": "duplicate tx.begin",
                    "rebuild_invalid_seq": 1,
                    "rebuild_observed_mismatch": {
                        "drift_reason": "duplicate tx.begin",
                        "last_applied_seq": 1,
                        "active_tx_id": "none",
                        "active_ticket_id": "none",
                        "invalid_reason": "duplicate tx.begin",
                        "invalid_event": {
                            "seq": 2,
                            "event_type": "tx.begin",
                            "tx_id": 1,
                            "ticket_id": "t-1",
                        },
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())
    repo_context.tx_state.unlink(missing_ok=True)

    result = ops.ops_capture_state(session_id="s1")

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "rebuild integrity drift detected"
    assert result["rebuild_warning"] == "duplicate tx.begin"
    assert result["recommended_action"].startswith(
        "Do not capture or trust canonical state until the invalid transaction history"
    )
    assert result["rebuild_observed_mismatch"]["invalid_reason"] == "duplicate tx.begin"
    assert result["rebuild_observed_mismatch"]["active_tx_id"] == "none"
    assert result["rebuild_observed_mismatch"]["active_ticket_id"] == "none"


def test_ops_handoff_export_defaults_to_tx_begin_without_canonical_event_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["next_step"] == "tx.begin"


def test_ops_handoff_export_uses_materialized_state_when_rebuild_has_duplicate_begin_drift(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": "drifted-tx",
                        "ticket_id": "drifted-ticket",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "drift-step",
                        "last_completed_step": "",
                        "next_action": "tx.commit.start",
                        "semantic_summary": "Drifted rebuild should not drive handoff.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "passed",
                            "last_result": {"ok": True},
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "none",
                    },
                    "rebuild_warning": "duplicate tx.begin",
                    "rebuild_invalid_seq": 1,
                    "rebuild_observed_mismatch": {
                        "drift_reason": "duplicate tx.begin",
                        "last_applied_seq": 1,
                        "active_tx_id": "none",
                        "active_ticket_id": "none",
                        "invalid_reason": "duplicate tx.begin",
                        "invalid_event": {
                            "seq": 2,
                            "event_type": "tx.begin",
                            "tx_id": 1,
                            "ticket_id": "t-1",
                        },
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    _set_active_tx(
        repo_context,
        tx_id="materialized-tx",
        ticket_id="materialized-ticket",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["current_task"] == "materialized-ticket"
    assert result["handoff"]["last_action"] == "Entered step resume-step"
    assert result["handoff"]["next_step"] == "tx.verify.start"
    assert result["handoff"]["compact_context"] == "Entered step resume-step"
    assert result["handoff"]["integrity_status"] == "blocked"
    assert result["handoff"]["blocked_reason"] == "duplicate tx.begin"
    assert result["handoff"]["recommended_action"].startswith(
        "Do not treat canonical state as healthy; inspect the invalid event metadata"
    )
    assert (
        result["handoff"]["rebuild_observed_mismatch"]["invalid_reason"]
        == "duplicate tx.begin"
    )


def test_ops_task_summary_uses_failure_reason_and_truncates(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "failed",
        "last_result": {"error": "verification failed in detail"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=60)

    assert result["ok"] is True
    assert result["summary"]["failure_reason"] == "verification failed in detail"
    assert len(result["text"]) <= 60


def test_ops_observability_summary_without_events_or_errors(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(session_id="s1", max_events=0, max_chars=80)

    assert result["ok"] is True
    assert result["max_events"] == 20
    assert result["max_chars"] == 80
    assert result["summary"]["recent_events"] == []
    assert repo_context.observability.exists()
    assert Path(result["text_path"]).exists()


def test_ops_observability_summary_includes_failure_reason_from_commit_state(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="verified",
        phase="verified",
        current_step="commit",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "failed",
        "last_result": {"error": "commit failed badly"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(session_id="s1", max_events=5, max_chars=200)

    assert result["ok"] is True
    assert result["summary"]["failure_reason"] == "commit failed badly"
    assert "failure_reason: commit failed badly" in result["text"]


def test_ops_observability_summary_skips_failure_lines_when_error_is_empty(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "not_started",
        "last_result": None,
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_observability_summary(session_id=None, max_events=5, max_chars=200)

    assert result["ok"] is True
    assert result["summary"]["session_id"] == ""
    assert "- failure_reason:" not in result["text"]
    assert "- last_error:" not in result["text"]


def test_ops_task_summary_uses_empty_last_verification_for_non_dict_result(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "failed",
        "last_result": "bad-result",
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=200)

    assert result["ok"] is True
    assert result["summary"]["last_verification"] == {}


def test_ops_resume_brief_uses_defaults_when_no_active_transaction(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=None)

    assert result["ok"] is True
    assert result["max_chars"] == 400
    assert "- can_start_new_ticket: yes" in result["brief"]


def test_ops_resume_brief_defaults_to_safe_no_active_transaction_view_when_rebuild_drifts(
    repo_context, state_store, state_rebuilder
):
    class DriftingRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": "drifted-tx",
                        "ticket_id": "drifted-ticket",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "drift-step",
                        "last_completed_step": "",
                        "next_action": "tx.commit.start",
                        "semantic_summary": "Drifted rebuild should not drive resume guidance.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "passed",
                            "last_result": {"ok": True},
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "active_candidate",
                    },
                    "rebuild_warning": "duplicate tx.begin",
                    "rebuild_invalid_seq": 1,
                    "rebuild_observed_mismatch": {
                        "drift_reason": "duplicate tx.begin",
                        "last_applied_seq": 1,
                        "active_tx_id": "none",
                        "active_ticket_id": "none",
                        "invalid_reason": "duplicate tx.begin",
                        "invalid_event": {
                            "seq": 2,
                            "event_type": "tx.begin",
                            "tx_id": 1,
                            "ticket_id": "t-1",
                        },
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    repo_context.tx_state.unlink(missing_ok=True)
    ops = _build_ops_tools(repo_context, state_store, DriftingRebuilder())

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    assert "- can_start_new_ticket: no" in result["brief"]
    assert "- status: blocked" in result["brief"]
    assert "- blocked_reason: duplicate tx.begin" in result["brief"]
    assert "- invalid_reason: duplicate tx.begin" in result["brief"]
    assert "- recommended_action:" in result["brief"]
    assert (
        "inspect rebuild_invalid_event and rebuild_observed_mismatch" in result["brief"]
    )
    assert "- active_ticket:" not in result["brief"]


def test_ops_resume_brief_ignores_ticket_only_active_transaction(
    repo_context, state_store, state_rebuilder
):
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    assert "- ticket_id: t-1" in result["brief"]
    assert "- can_start_new_ticket: yes" in result["brief"]
    assert "- active_ticket:" not in result["brief"]


def test_ops_task_summary_defaults_when_state_values_are_missing(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )
    tx_state["active_tx"]["semantic_summary"] = ""
    tx_state["active_tx"]["next_action"] = ""
    tx_state["active_tx"]["verify_state"] = "bad"
    tx_state["active_tx"]["commit_state"] = None
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_task_summary(session_id="s1", max_chars=200)

    assert result["ok"] is True
    assert result["summary"]["task_status"] == ""
    assert result["summary"]["next_step"] == "resume-step"
    assert result["summary"]["verification_status"] == ""
    assert result["summary"]["failure_reason"] == ""


def test_ops_observability_summary_uses_txt_suffix_when_path_has_no_suffix(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.observability.unlink(missing_ok=True)
    text_path = repo_context.observability.parent / (
        repo_context.observability.name + ".txt"
    )
    text_path.unlink(missing_ok=True)
    repo_context.observability = repo_context.observability.parent / "observability"

    result = ops.ops_observability_summary(session_id="s1", max_events=1, max_chars=80)

    assert result["ok"] is True
    assert result["text_path"].endswith("observability.txt")
    assert Path(result["text_path"]).exists()


def test_ops_compact_context_uses_commit_summary_and_error_fields(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="verified",
        phase="verified",
        current_step="commit",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "failed",
        "last_result": {
            "error": "commit failed badly",
            "sha": "abc123",
        },
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_compact_context(max_chars=200, include_diff=False)

    assert result["ok"] is True
    assert "verification_status: passed" in result["compact_context"]
    assert "last_commit: abc123" in result["compact_context"]
    assert "last_error: commit failed badly" in result["compact_context"]


def test_ops_end_task_copies_verify_and_commit_state_into_response_when_loaded_response_state_is_empty(
    repo_context, state_store, state_rebuilder, monkeypatch
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    tx_state = _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="committed",
        phase="committed",
        current_step="t-1",
        session_id="s1",
    )
    tx_state["active_tx"]["verify_state"] = {
        "status": "passed",
        "last_result": {"ok": True},
    }
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"sha": "abc123"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    original_load = ops._load_tx_state

    def patched_load():
        if getattr(patched_load, "called", False):
            return {"active_tx": {}}
        patched_load.called = True
        return original_load()

    patched_load.called = False
    monkeypatch.setattr(ops, "_load_tx_state", patched_load)

    result = ops.ops_end_task(
        summary="done",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["verify_status"] == "passed"
    assert result["commit_status"] == "passed"


def test_emit_tx_event_returns_none_when_append_fallback_cannot_derive_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    class AppendSaveRebuilder:
        def __init__(self):
            self.calls = 0

        def rebuild_tx_state(self):
            self.calls += 1
            if self.calls == 1:
                return {
                    "ok": True,
                    "state": {
                        "schema_version": "0.4.0",
                        "active_tx": {
                            "tx_id": 1,
                            "ticket_id": "t-1",
                            "status": "checking",
                            "phase": "checking",
                            "current_step": "resume-step",
                            "session_id": "s1",
                        },
                        "last_applied_seq": 1,
                        "integrity": {
                            "state_hash": "test-hash",
                            "rebuilt_from_seq": 1,
                            "drift_detected": True,
                            "active_tx_source": "active_candidate",
                        },
                        "updated_at": "2026-03-08T00:00:00+00:00",
                    },
                }
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "session_id": "s1",
                    },
                    "last_applied_seq": 2,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 2,
                        "drift_detected": False,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    _set_active_tx(
        repo_context,
        tx_id=1,
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    repo_context.tx_state.unlink(missing_ok=True)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        json.dumps(
            {
                "seq": 1,
                "ts": "2026-03-09T08:33:10+00:00",
                "tx_id": 1,
                "ticket_id": "t-1",
                "event_type": "tx.begin",
                "phase": "in-progress",
                "step_id": "none",
                "actor": {"tool": "test"},
                "session_id": "s1",
                "payload": {"ticket_id": "t-1", "ticket_title": "Build"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rebuilder = AppendSaveRebuilder()
    ops = _build_ops_tools(repo_context, state_store, rebuilder)

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "append then save"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id=None,
    )

    assert result is None
    assert repo_context.tx_state.exists() is False


def test_require_active_tx_rejects_matching_ticket_without_resume_permission(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "cannot emit tx.begin for an already-active non-terminal transaction; "
            "resume it with task update semantics instead"
        ),
    ):
        ops._require_active_tx("t-1", allow_resume=False)


def test_require_active_tx_treats_non_exact_tx_string_shapes_as_mismatch(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id="ticket-x",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=tx-123, "
            "requested_task=123, active_ticket=ticket-x, status=checking, "
            "next_action=tx.verify.start. Resume or complete the active "
            "transaction before starting a new ticket."
        ),
    ):
        ops._require_active_tx("123")


def test_ops_add_file_intent_requires_path_operation_and_purpose(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_add_file_intent(
            path=" ",
            operation="update",
            purpose="implement helper",
            task_id="t-1",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="operation is required"):
        ops.ops_add_file_intent(
            path="src/file.py",
            operation=" ",
            purpose="implement helper",
            task_id="t-1",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="purpose is required"):
        ops.ops_add_file_intent(
            path="src/file.py",
            operation="update",
            purpose=" ",
            task_id="t-1",
            session_id="s1",
        )


def test_ops_update_file_intent_requires_path_and_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_update_file_intent(
            path=" ",
            state="applied",
            task_id="t-1",
            session_id="s1",
        )

    with pytest.raises(ValueError, match="state is required"):
        ops.ops_update_file_intent(
            path="src/file.py",
            state=" ",
            task_id="t-1",
            session_id="s1",
        )


def test_ops_complete_file_intent_requires_path(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="path is required"):
        ops.ops_complete_file_intent(
            path=" ",
            task_id="t-1",
            session_id="s1",
        )


def test_ops_start_task_reuses_active_ticket_id_when_materialized_ticket_is_blank(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="tx-123",
        ticket_id=" ",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    result = ops.ops_start_task(title="Build", session_id="s1")

    assert result["ok"] is True
    assert result["payload"]["task_id"] == "tx-123"
    assert result["current_step"] == "resume-step"
    assert _read_tx_events(repo_context) == []


def test_ops_observability_summary_includes_artifacts_section_when_summary_artifacts_present(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.observability.parent.mkdir(parents=True, exist_ok=True)
    repo_context.observability.write_text(
        json.dumps(
            {
                "ts": "2026-03-09T08:33:10+00:00",
                "session_id": "s1",
                "recent_events": [],
                "failure_reason": "",
                "last_error": "",
                "verification_status": "",
                "artifacts": ["handoff.json", "observability.txt"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = ops.ops_observability_summary(session_id="s1", max_events=1, max_chars=400)

    assert result["ok"] is True
    assert result["summary"]["artifacts"] == []
    text = Path(result["text_path"]).read_text(encoding="utf-8")
    assert text.startswith("observability_summary:")


def test_ops_helpers_cover_identifier_and_terminal_branches(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    assert ops._normalize_tx_identifier(None) == ""
    assert ops._normalize_tx_identifier(" none ") == ""
    assert ops._normalize_tx_identifier(" t-1 ") == "t-1"

    assert ops._is_terminal_active_tx({"status": "done"}) is True
    assert ops._is_terminal_active_tx({"phase": "blocked"}) is True
    assert ops._is_terminal_active_tx({"_terminal": True}) is True
    assert (
        ops._is_terminal_active_tx({"status": "checking", "phase": "checking"}) is False
    )

    identity = ops._active_tx_identity({"tx_id": 0, "ticket_id": " t-2 "})
    assert identity == {
        "tx_id": "0",
        "ticket_id": "t-2",
        "canonical_id": "0",
        "has_canonical_tx": True,
    }

    identity = ops._active_tx_identity({"tx_id": 1, "ticket_id": " t-2 "})
    assert identity == {
        "tx_id": "1",
        "ticket_id": "t-2",
        "canonical_id": "1",
        "has_canonical_tx": True,
    }


def test_require_active_tx_allow_resume_returns_requested_id(
    repo_context, state_store, state_rebuilder
):
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    active_tx, resolved_id = ops._require_active_tx("t-1", allow_resume=True)

    assert active_tx["tx_id"] == "t-1"
    assert resolved_id == "t-1"


def test_emit_tx_event_returns_none_when_no_identifier(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "task", "description": "noop"},
        title="   ",
        task_id="   ",
        phase="in-progress",
        step_id="task",
        session_id="s1",
        agent_id=None,
    )

    assert result is None


def test_emit_tx_event_uses_append_and_rebuild_save_when_materialized_state_missing(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    repo_context.tx_state.unlink(missing_ok=True)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "from append"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id="agent-1",
    )

    assert result is not None
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["actor"]["agent_id"] == "agent-1"

    saved_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved_state["active_tx"]["tx_id"] == 1
    assert saved_state["active_tx"]["ticket_id"] == "t-1"


def test_emit_tx_event_uses_rebuild_state_when_materialized_state_lacks_identity(
    repo_context, state_store, state_rebuilder
):
    tx_state = _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="none",
        status="planned",
        phase="planned",
        current_step="none",
        session_id="",
    )
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "from rebuild"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id="agent-1",
    )

    assert result is not None
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["actor"]["agent_id"] == "agent-1"

    saved_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    assert saved_state["active_tx"]["tx_id"] == 1
    assert saved_state["active_tx"]["status"] == "checking"
    assert saved_state["active_tx"]["current_step"] == "resume-step"


def test_emit_tx_event_appends_without_state_save_when_rebuild_drifts(
    repo_context, state_store, state_rebuilder
):
    class DriftRebuilder:
        def rebuild_tx_state(self):
            return {
                "ok": True,
                "state": {
                    "schema_version": "0.4.0",
                    "active_tx": {
                        "tx_id": 1,
                        "ticket_id": "t-1",
                        "status": "checking",
                        "phase": "checking",
                        "current_step": "resume-step",
                        "last_completed_step": "",
                        "next_action": "tx.verify.start",
                        "semantic_summary": "Resume work.",
                        "user_intent": None,
                        "session_id": "s1",
                        "verify_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "commit_state": {
                            "status": "not_started",
                            "last_result": None,
                        },
                        "file_intents": [],
                    },
                    "last_applied_seq": 1,
                    "integrity": {
                        "state_hash": "test-hash",
                        "rebuilt_from_seq": 1,
                        "drift_detected": True,
                        "active_tx_source": "active_candidate",
                    },
                    "updated_at": "2026-03-08T00:00:00+00:00",
                },
            }

    repo_context.tx_state.unlink(missing_ok=True)
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")
    ops = _build_ops_tools(repo_context, state_store, DriftRebuilder())

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "drift append"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id=None,
    )

    assert result is None
    events = _read_tx_events(repo_context)
    assert events == []
    assert repo_context.tx_state.exists() is False


def test_emit_tx_event_returns_none_when_non_begin_has_no_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="none",
        ticket_id="t-1",
        status="checking",
        phase="checking",
        current_step="resume-step",
        session_id="s1",
    )

    result = ops._emit_tx_event(
        event_type="tx.step.enter",
        payload={"step_id": "resume-step", "description": "missing tx id"},
        title="t-1",
        task_id="t-1",
        phase="checking",
        step_id="resume-step",
        session_id="s1",
        agent_id=None,
    )

    assert result is None


def test_truncate_text_variants():
    assert truncate_text(None) is None
    assert truncate_text("x", limit=0) == ""
    assert truncate_text("ok", limit=10) == "ok"
    assert truncate_text("x" * 10, limit=5).endswith("...(truncated)")


def test_build_compact_context_includes_diff():
    state = {"last_action": "done", "verification_status": "passed"}
    summary = build_compact_context(state, "diff", 200)
    assert "diff_stat" in summary
    assert "done" in summary


def test_build_compact_context_defaults_when_empty():
    assert build_compact_context({}, None, 50) == "no recent state available"


def test_summarize_result_truncates():
    result = summarize_result({"text": "x" * 3000}, limit=10)
    assert result["truncated"] is True


def test_summarize_result_preserves_small_serializable_value():
    result = summarize_result({"ok": True}, limit=100)
    assert result == {"ok": True}


def test_summarize_result_falls_back_to_string_for_non_serializable_value():
    result = summarize_result({"bad": {1, 2, 3}}, limit=20)
    assert isinstance(result, dict)
    assert "bad" in result
    assert isinstance(result["bad"], set)


def test_ops_start_task_requires_title(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="title is required"):
        ops.ops_start_task(title="  ")


def test_ops_start_task_zero_event_baseline_requires_task_id_for_bootstrap(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="task_id is required to bootstrap tx.begin"):
        ops.ops_start_task(title="Build", session_id="s1")


def test_ops_update_task_requires_status_or_note(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="status or note is required"):
        ops.ops_update_task()


def test_ops_update_task_with_note_only_uses_active_task_and_default_phase(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_update_task(note="note only", session_id="s1")

    assert result["ok"] is True
    assert result["payload"]["task_id"] == "t-1"
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["phase"] == "in-progress"
    assert events[-1]["payload"]["description"] == "note only"


def test_ops_end_task_terminal_guidance_does_not_require_followup(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["status"] = "committed"
    tx_state["active_tx"]["phase"] = "committed"
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"sha": "abc123"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = ops.ops_end_task(
        summary="done",
        next_action="next",
        status="done",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "done"
    assert result["canonical_phase"] == "done"
    assert result["tx_status"] == "done"
    assert result["tx_phase"] == "done"
    assert result["terminal"] is True
    assert result["requires_followup"] is False
    assert result["followup_tool"] is None
    assert result["next_action"] == "tx.begin"
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "t-1"
    assert result["can_start_new_ticket"] is True
    assert result["resume_required"] is False


def test_ops_update_task_nonterminal_guidance_keeps_resume_state_consistent(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_update_task(
        status="checking",
        note="review guidance consistency",
        session_id="s1",
    )

    assert result["ok"] is True
    assert result["canonical_status"] == "checking"
    assert result["canonical_phase"] == "checking"
    assert result["tx_status"] == "checking"
    assert result["tx_phase"] == "checking"
    assert result["terminal"] is False
    assert result["requires_followup"] is True
    assert result["followup_tool"] is None
    assert result["next_action"] == "tx.verify.start"
    assert result["active_tx_id"] == 1
    assert result["active_ticket_id"] == "t-1"
    assert result["current_step"] == "t-1"
    assert result["can_start_new_ticket"] is False
    assert result["resume_required"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["payload"]["step_id"] == "t-1"


def test_ops_update_task_with_done_status_requires_ops_end_task(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    with pytest.raises(ValueError, match="use ops_end_task for terminal done state"):
        ops.ops_update_task(status="done", note="wrap up", session_id="s1")


def test_ops_end_task_requires_summary(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="summary is required"):
        ops.ops_end_task(summary=" ")


def test_ops_end_task_defaults_to_done_phase_and_omits_blank_next_action(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")
    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    tx_state["active_tx"]["status"] = "committed"
    tx_state["active_tx"]["phase"] = "committed"
    tx_state["active_tx"]["commit_state"] = {
        "status": "passed",
        "last_result": {"sha": "abc123"},
    }
    repo_context.tx_state.write_text(
        json.dumps(tx_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = ops.ops_end_task(summary="done", next_action="   ", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.end.done"
    assert events[-1]["phase"] == "done"
    assert "next_action" not in events[-1]["payload"]


def test_ops_end_task_emits_blocked_reason_payload(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id=1, session_id="s1")

    result = ops.ops_end_task(
        summary="waiting on review",
        status="blocked",
        task_id="t-1",
        session_id="s1",
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.end.blocked"
    assert events[-1]["payload"]["summary"] == "waiting on review"
    assert events[-1]["payload"]["reason"] == "waiting on review"
