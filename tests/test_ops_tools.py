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


def _begin_tx(
    state_store, state_rebuilder, tx_id="t-1", session_id="s1", title="Build"
):
    state_store.repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    state_store.repo_context.tx_event_log.write_text("", encoding="utf-8")
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_event_append_and_state_save(
        tx_id=tx_id,
        ticket_id=tx_id,
        event_type="tx.begin",
        phase="in-progress",
        step_id="none",
        actor={"tool": "test"},
        session_id=session_id,
        payload={"ticket_id": tx_id, "ticket_title": title},
        state=rebuild["state"],
    )


def _set_active_tx(
    repo_context,
    *,
    tx_id: str = "t-1",
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
                        "tx_id": "t-1",
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
                        "tx_id": "t-1",
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
    events = _read_tx_events(repo_context)
    event_types = [event["event_type"] for event in events]
    assert event_types == ["tx.begin", "tx.step.enter"]
    assert events[0]["payload"]["ticket_id"] == "t-1"
    assert events[0]["payload"]["ticket_title"] == "Build"
    assert events[1]["payload"]["step_id"] == "t-1"
    assert events[1]["payload"]["description"] == "task started"


def test_ops_start_task_requires_session_id(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_start_task(title="Build", task_id="t-1", session_id="")


def test_ops_start_task_uses_explicit_status_for_phase(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_start_task(
        title="Build", task_id="t-1", session_id="s1", status="checking"
    )

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.begin", "tx.step.enter"]
    assert events[0]["phase"] == "checking"
    assert events[1]["phase"] == "checking"


def test_ops_start_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2"
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_start_task_records_step_after_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    event_types = [event["event_type"] for event in events]
    assert event_types == ["tx.begin", "tx.step.enter"]
    step_event = events[-1]
    assert step_event["tx_id"] == "t-1"
    assert step_event["session_id"] == "s1"
    assert step_event["payload"]["step_id"] == "t-1"
    assert step_event["payload"]["description"] == "task started"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


def test_ops_start_task_prefers_materialized_state_over_rebuild_for_step_entry(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _set_active_tx(
        repo_context,
        tx_id="t-1",
        ticket_id="t-1",
        status="in-progress",
        phase="in-progress",
        current_step="resume-step",
        session_id="s1",
    )
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text("", encoding="utf-8")

    result = ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert [event["event_type"] for event in events] == ["tx.step.enter"]
    assert events[0]["tx_id"] == "t-1"
    assert events[0]["ticket_id"] == "t-1"
    assert events[0]["payload"]["step_id"] == "t-1"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


def test_ops_start_task_uses_ticket_id_when_tx_id_is_none(
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

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")


def test_ops_start_task_rejects_mismatch_against_active_ticket_id_when_tx_id_is_none(
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

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=unknown, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_start_task(title="Build", task_id="t-2", session_id="s1")


def test_ops_update_task_uses_ticket_id_when_tx_id_is_none(
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
        ops.ops_update_task(status="checking", note="step", session_id="s1")


def test_ops_update_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_update_task(status="checking", note="step", session_id="s1")


def test_ops_update_task_requires_session_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_update_task(
            status="checking", note="step", task_id="t-1", session_id=""
        )


def test_ops_update_task_falls_back_to_active_tx_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    ops.ops_update_task(status="blocked", note="waiting", session_id="s1")

    events = _read_tx_events(repo_context)
    update_events = [
        event
        for event in events
        if event["event_type"] == "tx.step.enter"
        and event.get("payload", {}).get("description") == "waiting"
    ]
    assert update_events
    assert update_events[-1]["tx_id"] == "t-1"
    assert update_events[-1]["session_id"] == "s1"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["status"] == "in-progress"
    assert active_tx["phase"] == "in-progress"
    assert active_tx["current_step"] == "blocked"
    assert active_tx["next_action"] == "tx.verify.start"


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
    assert [event["event_type"] for event in events] == ["tx.step.enter"]
    assert events[0]["tx_id"] == "t-1"
    assert events[0]["ticket_id"] == "t-1"
    assert events[0]["payload"]["description"] == "step"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


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
    assert [event["event_type"] for event in events] == ["tx.end.done"]
    assert events[0]["tx_id"] == "t-1"
    assert events[0]["ticket_id"] == "t-1"
    assert events[0]["payload"]["summary"] == "done"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["tx_id"] == "t-1"
    assert active_tx["ticket_id"] == "t-1"
    assert active_tx["status"] == "done"
    assert active_tx["phase"] == "done"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["session_id"] == "s1"
    assert active_tx["next_action"] == "tx.end.done"
    assert tx_state["last_applied_seq"] == events[-1]["seq"]


def test_ops_update_task_rejects_mismatched_task_id(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_update_task(
            status="checking",
            note="step",
            task_id="t-2",
            session_id="s1",
        )


def test_ops_update_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
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
    _begin_tx(state_store, state_rebuilder, tx_id="p1-t1", session_id="s1")
    ops.ops_update_task(
        status="checking",
        note="step",
        task_id="p1-t1",
        session_id="s1",
    )

    result = ops.ops_resume_brief(max_chars=400)

    assert result["ok"] is True
    brief = result["brief"]
    assert "- ticket_id: p1-t1" in brief
    assert "- status: checking" in brief
    assert "- next_action: tx.verify.start" in brief
    assert "- can_start_new_ticket: no" in brief
    assert (
        "- reason: active transaction exists and must be resumed before starting another ticket"
        in brief
    )


def test_ops_update_task_records_user_intent(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_update_task(
        status="checking",
        note="step",
        task_id="t-1",
        session_id="s1",
        user_intent="continue",
    )

    assert result["ok"] is True

    events = _read_tx_events(repo_context)
    tx_events = [event["event_type"] for event in events]
    assert tx_events == ["tx.begin", "tx.step.enter", "tx.user_intent.set"]
    assert events[-1]["payload"]["user_intent"] == "continue"

    tx_state = json.loads(repo_context.tx_state.read_text(encoding="utf-8"))
    active_tx = tx_state["active_tx"]
    assert active_tx["user_intent"] == "continue"
    assert active_tx["semantic_summary"].startswith("Entered step")
    assert active_tx["status"] == "checking"
    assert active_tx["phase"] == "checking"
    assert active_tx["current_step"] == "t-1"
    assert active_tx["next_action"] == "tx.verify.start"


def test_ops_end_task_requires_prior_tx_begin(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_end_task(summary="done", session_id="s1")


def test_ops_end_task_mismatch_error_includes_recovery_guidance(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(
        ValueError,
        match=(
            "tx_id does not match active transaction: active_tx=t-1, requested_task=t-2, "
            "active_ticket=t-1, status=in-progress, next_action=tx.verify.start. "
            "Resume or complete the active transaction before starting a new ticket."
        ),
    ):
        ops.ops_end_task(summary="done", task_id="t-2", session_id="s1")


def test_ops_end_task_requires_session_id(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    with pytest.raises(ValueError, match="session_id is required"):
        ops.ops_end_task(summary="done", task_id="t-1", session_id="")


def test_ops_end_task_emits_terminal_event_and_updates_state(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
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
    assert events[0]["tx_id"] == "t-2"
    assert events[0]["ticket_id"] == "t-2"
    assert events[1]["tx_id"] == "t-2"
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

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops.ops_start_task(title="Restart", session_id="s1")


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


def test_ops_task_summary_emits_journal(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_task_summary(session_id="s1", max_chars=40)
    assert result["ok"] is True
    assert result["summary"]["task_id"] == "t-1"
    assert len(result["text"]) <= 40


def test_ops_observability_summary_includes_artifacts(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")
    ops.ops_update_task(
        status="blocked",
        note="waiting",
        task_id="t-1",
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
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
    ops.ops_start_task(title="Build", task_id="t-1", session_id="s1")

    result = ops.ops_resume_brief(max_chars=20)
    assert result["ok"] is True
    assert len(result["brief"]) <= 20


def test_ops_capture_state_updates_tx_state(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")
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
                        "tx_id": "t-1",
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
                        "tx_id": "none",
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
                        "tx_id": "t-1",
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
                        "tx_id": "none",
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
                            "tx_id": "t-1",
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
    assert result["active_tx"]["tx_id"] == "none"
    assert result["active_tx"]["ticket_id"] == "none"
    assert result["active_tx"]["next_action"] == "tx.begin"


def test_ops_handoff_export_defaults_to_tx_begin_without_canonical_event_log(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_handoff_export()

    assert result["ok"] is True
    assert result["handoff"]["next_step"] == "tx.begin"


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


def test_ops_resume_brief_uses_defaults_when_no_active_transaction(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)

    result = ops.ops_resume_brief(max_chars=None)

    assert result["ok"] is True
    assert result["max_chars"] == 400
    assert "- can_start_new_ticket: yes" in result["brief"]


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

    identity = ops._active_tx_identity({"tx_id": "none", "ticket_id": " t-2 "})
    assert identity == {
        "tx_id": "",
        "ticket_id": "t-2",
        "canonical_id": "t-2",
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
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

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
    assert saved_state["active_tx"]["tx_id"] == "t-1"
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
                        "tx_id": "t-1",
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

    with pytest.raises(ValueError, match="tx.begin required before other events"):
        ops._emit_tx_event(
            event_type="tx.step.enter",
            payload={"step_id": "resume-step", "description": "drift append"},
            title="t-1",
            task_id="t-1",
            phase="checking",
            step_id="resume-step",
            session_id="s1",
            agent_id=None,
        )

    events = _read_tx_events(repo_context)
    assert events == []
    assert repo_context.tx_state.exists() is False


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

    with pytest.raises(ValueError, match="tx.begin required before other events"):
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
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_update_task(note="note only", session_id="s1")

    assert result["ok"] is True
    assert result["payload"]["task_id"] == "t-1"
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["phase"] == "in-progress"
    assert events[-1]["payload"]["description"] == "note only"
    assert events[-1]["payload"]["step_id"] == "task"


def test_ops_update_task_with_done_status_keeps_non_terminal_phase_until_end(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

    result = ops.ops_update_task(status="done", note="wrap up", session_id="s1")

    assert result["ok"] is True
    events = _read_tx_events(repo_context)
    assert events[-1]["event_type"] == "tx.step.enter"
    assert events[-1]["phase"] == "in-progress"
    assert events[-1]["payload"]["step_id"] == "done"


def test_ops_end_task_requires_summary(repo_context, state_store, state_rebuilder):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    with pytest.raises(ValueError, match="summary is required"):
        ops.ops_end_task(summary=" ")


def test_ops_end_task_defaults_to_done_phase_and_omits_blank_next_action(
    repo_context, state_store, state_rebuilder
):
    ops = _build_ops_tools(repo_context, state_store, state_rebuilder)
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

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
    _begin_tx(state_store, state_rebuilder, tx_id="t-1", session_id="s1")

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
