from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

TERMINAL_STATUSES = {"done", "blocked"}
END_TASK_ACTIONS = {"tx.end.done", "tx.end.blocked"}
DEFAULT_FAILURE_ACTIONS = {
    "begin_required": {
        "recoverable": True,
        "recommended_next_tool": "ops_start_task",
        "recommended_action": "Start or resume the canonical transaction before emitting lifecycle events.",
    },
    "resume_required": {
        "recoverable": True,
        "recommended_next_tool": "ops_update_task",
        "recommended_action": "Resume or complete the active transaction before starting a different ticket.",
    },
    "terminal_transaction": {
        "recoverable": False,
        "recommended_next_tool": "ops_start_task",
        "recommended_action": "Do not emit more lifecycle events for a terminal transaction; start a new ticket only when canonical state allows it.",
    },
    "invalid_ordering": {
        "recoverable": True,
        "recommended_next_tool": "ops_update_task",
        "recommended_action": "Follow the canonical lifecycle ordering and retry from the required prerequisite step.",
    },
    "verify_failed": {
        "recoverable": True,
        "recommended_next_tool": "repo_verify",
        "recommended_action": "Repair the verification failure and rerun verification before attempting commit.",
    },
    "commit_required": {
        "recoverable": True,
        "recommended_next_tool": "repo_commit",
        "recommended_action": "Complete the commit workflow before attempting terminal completion.",
    },
    "integrity_blocked": {
        "recoverable": False,
        "recommended_next_tool": "tx_state_rebuild",
        "recommended_action": "Repair or replace the invalid canonical history before treating the transaction state as healthy.",
    },
    "tx_id_collision": {
        "recoverable": False,
        "recommended_next_tool": "tx_state_rebuild",
        "recommended_action": "Do not treat the collided history as healthy. Repair the historical log, assign future canonical tx_id values as opaque identifiers, and keep user-facing ticket labels separate from canonical transaction identity.",
    },
    "historical_repair_required": {
        "recoverable": False,
        "recommended_next_tool": "tx_state_rebuild",
        "recommended_action": "Historical repair is required before resume-safe automation can continue. Preserve the invalid event metadata, repair or replace the damaged canonical history, and avoid reusing human ticket labels as canonical tx_id values.",
    },
}


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


def _clean_optional_tx_id(value: Any) -> Optional[int]:
    return _clean_int(value)


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _active_tx_from_state(tx_state: Any) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    active_tx = state.get("active_tx")
    if isinstance(active_tx, dict):
        return dict(active_tx)
    return {}


def _verify_state_from_state(
    tx_state: Any, active_tx: Mapping[str, Any]
) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    verify_state = state.get("verify_state")
    if isinstance(verify_state, dict):
        return dict(verify_state)
    return {}


def _commit_state_from_state(
    tx_state: Any, active_tx: Mapping[str, Any]
) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    commit_state = state.get("commit_state")
    if isinstance(commit_state, dict):
        return dict(commit_state)
    return {}


def _failure_defaults(error_code: str) -> Dict[str, Any]:
    return dict(DEFAULT_FAILURE_ACTIONS.get(error_code, {}))


def _integrity_from_state(tx_state: Any) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    return _as_dict(state.get("integrity"))


def _resolved_status_phase_next_action(
    tx_state: Any,
    active_tx: Mapping[str, Any],
    *,
    canonical_status: Any = None,
    canonical_phase: Any = None,
    next_action: Any = None,
) -> tuple[str, str, str]:
    state = _as_dict(tx_state)
    tx_status = _clean_str(canonical_status) or _clean_str(state.get("status"))
    resolved_next_action = _clean_str(next_action) or _clean_str(
        state.get("next_action")
    )
    tx_phase = _clean_str(canonical_phase) or tx_status
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
    state = _as_dict(tx_state)
    active_tx = _active_tx_from_state(state)
    integrity = _integrity_from_state(state)
    verify_state = _verify_state_from_state(state, active_tx)
    commit_state = _commit_state_from_state(state, active_tx)

    tx_status, tx_phase, resolved_next_action = _resolved_status_phase_next_action(
        state,
        active_tx,
        canonical_status=canonical_status,
        canonical_phase=canonical_phase,
        next_action=next_action,
    )

    resolved_terminal = _clean_bool(terminal)
    if resolved_terminal is None:
        resolved_terminal = tx_status in TERMINAL_STATUSES

    resolved_followup_tool = _clean_optional_str(followup_tool)
    if resolved_followup_tool is None and resolved_next_action in END_TASK_ACTIONS:
        resolved_followup_tool = "ops_end_task"

    resolved_requires_followup = _clean_bool(requires_followup)
    if resolved_requires_followup is None:
        resolved_requires_followup = (
            bool(resolved_next_action) and not resolved_terminal
        )

    resolved_active_tx_id = _clean_optional_tx_id(active_tx_id)
    if resolved_active_tx_id is None:
        resolved_active_tx_id = _clean_optional_tx_id(active_tx.get("tx_id"))

    resolved_active_ticket_id = _clean_optional_str(active_ticket_id)
    if resolved_active_ticket_id is None:
        resolved_active_ticket_id = _clean_optional_str(active_tx.get("ticket_id"))

    resolved_current_step = _clean_optional_str(current_step)

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

    has_active_tx = (
        bool(active_tx)
        and resolved_active_tx_id is not None
        and resolved_active_ticket_id is not None
    )

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
    cleaned_error_code = _clean_str(error_code)
    if not cleaned_error_code:
        raise ValueError("error_code is required")
    cleaned_reason = _clean_str(reason)
    if not cleaned_reason:
        raise ValueError("reason is required")

    defaults = _failure_defaults(cleaned_error_code)
    resolved_recommended_next_tool = _clean_optional_str(recommended_next_tool)
    if resolved_recommended_next_tool is None:
        resolved_recommended_next_tool = _clean_optional_str(
            defaults.get("recommended_next_tool")
        )

    resolved_recommended_action = _clean_optional_str(recommended_action)
    if resolved_recommended_action is None:
        resolved_recommended_action = _clean_optional_str(
            defaults.get("recommended_action")
        )

    resolved_recoverable = (
        recoverable
        if isinstance(recoverable, bool)
        else bool(defaults.get("recoverable", False))
    )

    guidance = derive_workflow_guidance(tx_state, **guidance_overrides)

    response: Dict[str, Any] = {
        "ok": False,
        "error_code": cleaned_error_code,
        "reason": cleaned_reason,
        "recoverable": resolved_recoverable,
        "recommended_next_tool": resolved_recommended_next_tool,
        "recommended_action": resolved_recommended_action,
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


def build_structured_helper_failure(
    *,
    error_code: Any,
    reason: Any,
    tx_state: Any = None,
    recommended_next_tool: Any = None,
    recommended_action: Any = None,
    recoverable: Any = None,
    blocked: Any = None,
    rebuild_warning: Any = None,
    rebuild_invalid_seq: Any = None,
    rebuild_observed_mismatch: Any = None,
    **guidance_overrides: Any,
) -> Dict[str, Any]:
    cleaned_error_code = _clean_str(error_code)
    defaults = _failure_defaults(cleaned_error_code)
    resolved_recoverable = (
        recoverable
        if isinstance(recoverable, bool)
        else defaults.get("recoverable", False)
    )
    return build_failure_response(
        error_code=cleaned_error_code,
        reason=reason,
        tx_state=tx_state,
        recoverable=bool(resolved_recoverable),
        recommended_next_tool=(
            recommended_next_tool
            if recommended_next_tool is not None
            else defaults.get("recommended_next_tool")
        ),
        recommended_action=(
            recommended_action
            if recommended_action is not None
            else defaults.get("recommended_action")
        ),
        blocked=blocked,
        rebuild_warning=rebuild_warning,
        rebuild_invalid_seq=rebuild_invalid_seq,
        rebuild_observed_mismatch=rebuild_observed_mismatch,
        **guidance_overrides,
    )


def merge_response_data(
    base: Mapping[str, Any], extra: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    merged = dict(base)
    if extra:
        merged.update(dict(extra))
    return merged
