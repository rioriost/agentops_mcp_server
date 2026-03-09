import pytest

from agentops_mcp_server.workflow_response import (
    build_failure_response,
    build_guidance_from_active_tx,
    build_success_response,
    derive_workflow_guidance,
    merge_response_data,
)


def _tx_state(
    *,
    tx_id="tx-1",
    ticket_id="p1-t02",
    status="in-progress",
    phase="in-progress",
    next_action="tx.verify.start",
    current_step="p1-t02",
    verify_status="not_started",
    commit_status="not_started",
    drift_detected=False,
):
    return {
        "active_tx": {
            "tx_id": tx_id,
            "ticket_id": ticket_id,
            "status": status,
            "phase": phase,
            "next_action": next_action,
            "current_step": current_step,
            "verify_state": {
                "status": verify_status,
                "last_result": None,
            },
            "commit_state": {
                "status": commit_status,
                "last_result": None,
            },
        },
        "integrity": {
            "state_hash": "hash",
            "rebuilt_from_seq": 7,
            "drift_detected": drift_detected,
            "active_tx_source": "materialized",
        },
    }


def test_derive_workflow_guidance_reads_canonical_fields_from_state():
    guidance = derive_workflow_guidance(
        _tx_state(
            status="verified",
            phase="verified",
            next_action="tx.commit.start",
            current_step="verify",
            verify_status="passed",
            commit_status="not_started",
        )
    )

    assert guidance["canonical_status"] == "verified"
    assert guidance["canonical_phase"] == "verified"
    assert guidance["next_action"] == "tx.commit.start"
    assert guidance["terminal"] is False
    assert guidance["requires_followup"] is True
    assert guidance["followup_tool"] is None
    assert guidance["active_tx_id"] == "tx-1"
    assert guidance["active_ticket_id"] == "p1-t02"
    assert guidance["current_step"] == "verify"
    assert guidance["verify_status"] == "passed"
    assert guidance["commit_status"] == "not_started"
    assert guidance["integrity_status"] == "ok"
    assert guidance["can_start_new_ticket"] is False
    assert guidance["resume_required"] is True


def test_derive_workflow_guidance_marks_terminal_done_state():
    guidance = derive_workflow_guidance(
        _tx_state(
            status="done",
            phase="done",
            next_action="tx.end.done",
            verify_status="passed",
            commit_status="passed",
        )
    )

    assert guidance["canonical_status"] == "done"
    assert guidance["canonical_phase"] == "done"
    assert guidance["terminal"] is True
    assert guidance["requires_followup"] is False
    assert guidance["followup_tool"] == "ops_end_task"
    assert guidance["can_start_new_ticket"] is True
    assert guidance["resume_required"] is False


def test_derive_workflow_guidance_treats_committed_as_non_terminal_with_followup():
    guidance = derive_workflow_guidance(
        _tx_state(
            status="committed",
            phase="committed",
            next_action="tx.end.done",
            verify_status="passed",
            commit_status="passed",
        )
    )

    assert guidance["canonical_status"] == "committed"
    assert guidance["canonical_phase"] == "committed"
    assert guidance["terminal"] is False
    assert guidance["requires_followup"] is True
    assert guidance["followup_tool"] == "ops_end_task"
    assert guidance["can_start_new_ticket"] is False
    assert guidance["resume_required"] is True


def test_derive_workflow_guidance_handles_missing_or_invalid_state():
    guidance = derive_workflow_guidance(None)

    assert guidance["canonical_status"] == ""
    assert guidance["canonical_phase"] == ""
    assert guidance["next_action"] == ""
    assert guidance["terminal"] is False
    assert guidance["requires_followup"] is False
    assert guidance["followup_tool"] is None
    assert guidance["active_tx_id"] is None
    assert guidance["active_ticket_id"] is None
    assert guidance["current_step"] is None
    assert guidance["verify_status"] is None
    assert guidance["commit_status"] is None
    assert guidance["integrity_status"] is None
    assert guidance["can_start_new_ticket"] is True
    assert guidance["resume_required"] is False


def test_derive_workflow_guidance_ignores_none_tx_identity_values():
    guidance = derive_workflow_guidance(
        _tx_state(
            tx_id="none",
            ticket_id="none",
            status="checking",
            phase="checking",
        )
    )

    assert guidance["active_tx_id"] is None
    assert guidance["active_ticket_id"] is None
    assert guidance["can_start_new_ticket"] is True
    assert guidance["resume_required"] is False


def test_derive_workflow_guidance_reports_drifted_integrity_status():
    guidance = derive_workflow_guidance(_tx_state(drift_detected=True))

    assert guidance["integrity_status"] == "drift_detected"


def test_derive_workflow_guidance_allows_explicit_overrides():
    guidance = derive_workflow_guidance(
        _tx_state(),
        canonical_status="checking",
        canonical_phase="checking",
        next_action="tx.verify.pass",
        terminal=False,
        requires_followup=True,
        followup_tool="ops_end_task",
        can_start_new_ticket=False,
        resume_required=True,
        current_step="override-step",
        verify_status="running",
        commit_status="failed",
        integrity_status="custom",
        active_tx_id="override-tx",
        active_ticket_id="override-ticket",
    )

    assert guidance["canonical_status"] == "checking"
    assert guidance["canonical_phase"] == "checking"
    assert guidance["next_action"] == "tx.verify.pass"
    assert guidance["terminal"] is False
    assert guidance["requires_followup"] is True
    assert guidance["followup_tool"] == "ops_end_task"
    assert guidance["active_tx_id"] == "override-tx"
    assert guidance["active_ticket_id"] == "override-ticket"
    assert guidance["current_step"] == "override-step"
    assert guidance["verify_status"] == "running"
    assert guidance["commit_status"] == "failed"
    assert guidance["integrity_status"] == "custom"
    assert guidance["can_start_new_ticket"] is False
    assert guidance["resume_required"] is True


def test_build_success_response_includes_guidance_and_legacy_fields():
    response = build_success_response(
        tx_state=_tx_state(
            status="verified",
            phase="verified",
            next_action="tx.commit.start",
            current_step="verify",
            verify_status="passed",
        ),
        payload={"path": "src/example.py"},
        event={"event_type": "tx.verify.pass"},
    )

    assert response["ok"] is True
    assert response["payload"] == {"path": "src/example.py"}
    assert response["event"] == {"event_type": "tx.verify.pass"}
    assert response["canonical_status"] == "verified"
    assert response["canonical_phase"] == "verified"
    assert response["tx_status"] == "verified"
    assert response["tx_phase"] == "verified"
    assert response["next_action"] == "tx.commit.start"
    assert response["verify_status"] == "passed"
    assert response["active_tx_id"] == "tx-1"
    assert response["active_ticket_id"] == "p1-t02"


def test_build_success_response_can_skip_legacy_fields():
    response = build_success_response(
        tx_state=_tx_state(),
        include_legacy_guidance=False,
    )

    assert response["ok"] is True
    assert "tx_status" not in response
    assert "tx_phase" not in response
    assert response["canonical_status"] == "in-progress"
    assert response["canonical_phase"] == "in-progress"


def test_build_failure_response_includes_structured_recovery_fields():
    response = build_failure_response(
        error_code="integrity_drift",
        reason="rebuild integrity drift detected",
        tx_state=_tx_state(
            status="checking",
            phase="checking",
            next_action="fix and re-verify",
            current_step="verify",
            drift_detected=True,
        ),
        recoverable=False,
        recommended_next_tool="ops_capture_state",
        recommended_action="repair canonical history before resuming work",
        blocked=True,
        rebuild_warning="drift",
        rebuild_invalid_seq=11,
        rebuild_observed_mismatch={"expected": 10, "observed": 11},
    )

    assert response["ok"] is False
    assert response["error_code"] == "integrity_drift"
    assert response["reason"] == "rebuild integrity drift detected"
    assert response["recoverable"] is False
    assert response["recommended_next_tool"] == "ops_capture_state"
    assert (
        response["recommended_action"]
        == "repair canonical history before resuming work"
    )
    assert response["canonical_status"] == "checking"
    assert response["canonical_phase"] == "checking"
    assert response["tx_status"] == "checking"
    assert response["tx_phase"] == "checking"
    assert response["next_action"] == "fix and re-verify"
    assert response["terminal"] is False
    assert response["requires_followup"] is True
    assert response["followup_tool"] is None
    assert response["active_tx_id"] == "tx-1"
    assert response["active_ticket_id"] == "p1-t02"
    assert response["current_step"] == "verify"
    assert response["integrity_status"] == "drift_detected"
    assert response["blocked"] is True
    assert response["rebuild_warning"] == "drift"
    assert response["rebuild_invalid_seq"] == 11
    assert response["rebuild_observed_mismatch"] == {"expected": 10, "observed": 11}


def test_build_failure_response_defaults_optional_fields():
    response = build_failure_response(
        error_code="no_active_tx",
        reason="tx.begin required before other events",
    )

    assert response["ok"] is False
    assert response["recoverable"] is False
    assert response["recommended_next_tool"] is None
    assert response["recommended_action"] is None
    assert response["canonical_status"] == ""
    assert response["canonical_phase"] == ""
    assert response["next_action"] == ""
    assert response["terminal"] is False
    assert response["active_tx_id"] is None
    assert response["active_ticket_id"] is None
    assert response["current_step"] is None
    assert response["integrity_status"] is None
    assert response["blocked"] is False
    assert response["rebuild_warning"] is None
    assert response["rebuild_invalid_seq"] is None
    assert response["rebuild_observed_mismatch"] is None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "error_code is required"),
        ({"error_code": "x"}, "reason is required"),
    ],
)
def test_build_failure_response_requires_error_code_and_reason(kwargs, message):
    with pytest.raises(ValueError, match=message):
        build_failure_response(**kwargs)


def test_build_guidance_from_active_tx_wraps_active_tx_state():
    guidance = build_guidance_from_active_tx(
        {
            "tx_id": "tx-9",
            "ticket_id": "ticket-9",
            "status": "verified",
            "phase": "verified",
            "next_action": "tx.commit.start",
            "current_step": "step-9",
            "verify_state": {"status": "passed"},
            "commit_state": {"status": "not_started"},
        }
    )

    assert guidance["active_tx_id"] == "tx-9"
    assert guidance["active_ticket_id"] == "ticket-9"
    assert guidance["canonical_status"] == "verified"
    assert guidance["current_step"] == "step-9"


def test_merge_response_data_merges_extra_fields():
    merged = merge_response_data(
        {"ok": True, "canonical_status": "verified"},
        {"summary": "done", "canonical_phase": "verified"},
    )

    assert merged == {
        "ok": True,
        "canonical_status": "verified",
        "summary": "done",
        "canonical_phase": "verified",
    }


def test_merge_response_data_returns_copy_when_extra_missing():
    base = {"ok": True}
    merged = merge_response_data(base)

    assert merged == {"ok": True}
    assert merged is not base
