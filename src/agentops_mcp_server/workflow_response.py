from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

TERMINAL_STATUSES = {"done", "blocked"}
END_TASK_ACTIONS = {"tx.end.done", "tx.end.blocked"}


def _clean_str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _clean_optional_str(value: Any) -> Optional[str]:
    cleaned = _clean_str(value)
    return cleaned or None


def _clean_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    return None


def _clean_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _active_tx_from_state(tx_state: Any) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    return _as_dict(state.get("active_tx"))


def _verify_state_from_active_tx(active_tx: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_dict(active_tx.get("verify_state"))


def _commit_state_from_active_tx(active_tx: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_dict(active_tx.get("commit_state"))


def _integrity_from_state(tx_state: Any) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    return _as_dict(state.get("integrity"))


def _resolved_status_phase_next_action(
    active_tx: Mapping[str, Any],
    *,
    canonical_status: Any = None,
    canonical_phase: Any = None,
    next_action: Any = None,
) -> tuple[str, str, str]:
    tx_status = _clean_str(canonical_status) or _clean_str(active_tx.get("status"))
    tx_phase = (
        _clean_str(canonical_phase) or _clean_str(active_tx.get("phase")) or tx_status
    )
    resolved_next_action = _clean_str(next_action) or _clean_str(
        active_tx.get("next_action")
    )
    return tx_status, tx_phase, resolved_next_action


def derive_workflow_guidance(
    tx_state: Any,
    *,
    canonical_status: Any = None,
    canonical_phase: Any = None,
    next_action: Any = None,
    followup_tool: Any = None,
    terminal: Any = None,
    requires_followup: Any = None,
    can_start_new_ticket: Any = None,
    resume_required: Any = None,
    current_step: Any = None,
    verify_status: Any = None,
    commit_status: Any = None,
    integrity_status: Any = None,
    active_tx_id: Any = None,
    active_ticket_id: Any = None,
) -> Dict[str, Any]:
    active_tx = _active_tx_from_state(tx_state)
    integrity = _integrity_from_state(tx_state)
    verify_state = _verify_state_from_active_tx(active_tx)
    commit_state = _commit_state_from_active_tx(active_tx)

    tx_status, tx_phase, resolved_next_action = _resolved_status_phase_next_action(
        active_tx,
        canonical_status=canonical_status,
        canonical_phase=canonical_phase,
        next_action=next_action,
    )

    resolved_terminal = _clean_bool(terminal)
    if resolved_terminal is None:
        resolved_terminal = (
            tx_status in TERMINAL_STATUSES or tx_phase in TERMINAL_STATUSES
        )

    resolved_followup_tool = _clean_optional_str(followup_tool)
    if resolved_followup_tool is None and resolved_next_action in END_TASK_ACTIONS:
        resolved_followup_tool = "ops_end_task"

    resolved_requires_followup = _clean_bool(requires_followup)
    if resolved_requires_followup is None:
        resolved_requires_followup = (
            bool(resolved_next_action) and not resolved_terminal
        )

    resolved_active_tx_id = _clean_optional_str(active_tx_id)
    if resolved_active_tx_id is None:
        candidate = _clean_str(active_tx.get("tx_id"))
        if candidate and candidate != "none":
            resolved_active_tx_id = candidate

    resolved_active_ticket_id = _clean_optional_str(active_ticket_id)
    if resolved_active_ticket_id is None:
        candidate = _clean_str(active_tx.get("ticket_id"))
        if candidate and candidate != "none":
            resolved_active_ticket_id = candidate

    resolved_current_step = _clean_optional_str(current_step)
    if resolved_current_step is None:
        resolved_current_step = _clean_optional_str(active_tx.get("current_step"))

    resolved_verify_status = _clean_optional_str(verify_status)
    if resolved_verify_status is None:
        resolved_verify_status = _clean_optional_str(verify_state.get("status"))

    resolved_commit_status = _clean_optional_str(commit_status)
    if resolved_commit_status is None:
        resolved_commit_status = _clean_optional_str(commit_state.get("status"))

    resolved_integrity_status = _clean_optional_str(integrity_status)
    if resolved_integrity_status is None:
        if integrity.get("drift_detected") is True:
            resolved_integrity_status = "drift_detected"
        elif integrity:
            resolved_integrity_status = "ok"

    has_active_tx = bool(resolved_active_tx_id or resolved_active_ticket_id)

    resolved_resume_required = _clean_bool(resume_required)
    if resolved_resume_required is None:
        resolved_resume_required = has_active_tx and not resolved_terminal

    resolved_can_start_new_ticket = _clean_bool(can_start_new_ticket)
    if resolved_can_start_new_ticket is None:
        resolved_can_start_new_ticket = not has_active_tx or resolved_terminal

    return {
        "canonical_status": tx_status,
        "canonical_phase": tx_phase,
        "next_action": resolved_next_action,
        "terminal": resolved_terminal,
        "requires_followup": resolved_requires_followup,
        "followup_tool": resolved_followup_tool,
        "active_tx_id": resolved_active_tx_id,
        "active_ticket_id": resolved_active_ticket_id,
        "current_step": resolved_current_step,
        "verify_status": resolved_verify_status,
        "commit_status": resolved_commit_status,
        "integrity_status": resolved_integrity_status,
        "can_start_new_ticket": resolved_can_start_new_ticket,
        "resume_required": resolved_resume_required,
    }


def build_success_response(
    *,
    tx_state: Any = None,
    payload: Optional[Mapping[str, Any]] = None,
    event: Any = None,
    ok: bool = True,
    include_legacy_guidance: bool = True,
    **guidance_overrides: Any,
) -> Dict[str, Any]:
    response: Dict[str, Any] = {"ok": ok}

    if event is not None:
        response["event"] = event
    if payload is not None:
        response["payload"] = dict(payload)

    guidance = derive_workflow_guidance(tx_state, **guidance_overrides)
    response.update(guidance)

    if include_legacy_guidance:
        response.update(
            {
                "tx_status": guidance["canonical_status"],
                "tx_phase": guidance["canonical_phase"],
            }
        )

    return response


def build_failure_response(
    *,
    error_code: Any = None,
    reason: Any = None,
    tx_state: Any = None,
    recoverable: bool = False,
    recommended_next_tool: Any = None,
    recommended_action: Any = None,
    blocked: Any = None,
    rebuild_warning: Any = None,
    rebuild_invalid_seq: Any = None,
    rebuild_observed_mismatch: Any = None,
    include_legacy_guidance: bool = True,
    **guidance_overrides: Any,
) -> Dict[str, Any]:
    if not _clean_str(error_code):
        raise ValueError("error_code is required")
    if not _clean_str(reason):
        raise ValueError("reason is required")

    guidance = derive_workflow_guidance(tx_state, **guidance_overrides)

    response: Dict[str, Any] = {
        "ok": False,
        "error_code": _clean_str(error_code),
        "reason": _clean_str(reason),
        "recoverable": bool(recoverable),
        "recommended_next_tool": _clean_optional_str(recommended_next_tool),
        "recommended_action": _clean_optional_str(recommended_action),
        "canonical_status": guidance["canonical_status"],
        "canonical_phase": guidance["canonical_phase"],
        "next_action": guidance["next_action"],
        "terminal": guidance["terminal"],
        "active_tx_id": guidance["active_tx_id"],
        "active_ticket_id": guidance["active_ticket_id"],
        "current_step": guidance["current_step"],
        "integrity_status": guidance["integrity_status"],
        "blocked": bool(blocked) if isinstance(blocked, bool) else False,
        "rebuild_warning": rebuild_warning,
        "rebuild_invalid_seq": _clean_int(rebuild_invalid_seq),
        "rebuild_observed_mismatch": (
            dict(rebuild_observed_mismatch)
            if isinstance(rebuild_observed_mismatch, dict)
            else rebuild_observed_mismatch
        ),
    }

    if include_legacy_guidance:
        response.update(
            {
                "tx_status": guidance["canonical_status"],
                "tx_phase": guidance["canonical_phase"],
                "requires_followup": guidance["requires_followup"],
                "followup_tool": guidance["followup_tool"],
            }
        )

    return response


def build_guidance_from_active_tx(active_tx: Mapping[str, Any]) -> Dict[str, Any]:
    return derive_workflow_guidance({"active_tx": dict(active_tx)})


def merge_response_data(
    base: Mapping[str, Any], extra: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    merged = dict(base)
    if extra:
        merged.update(dict(extra))
    return merged
