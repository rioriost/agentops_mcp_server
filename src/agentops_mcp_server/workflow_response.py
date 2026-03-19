from __future__ import annotations

import json
from typing import Any, Callable, Dict, Literal, Mapping, Optional, TypeAlias, TypedDict

TERMINAL_STATUSES = {"done", "blocked"}
END_TASK_ACTIONS = {"tx.end.done", "tx.end.blocked"}
CANONICAL_IDLE_BASELINE = {
    "active_tx": None,
    "status": None,
    "next_action": "tx.begin",
    "verify_state": None,
    "commit_state": None,
    "semantic_summary": None,
}
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


class FailurePayload(TypedDict, total=False):
    error_code: str
    reason: str
    tx_state: Any
    recoverable: bool
    blocked: bool
    recommended_next_tool: str
    recommended_action: str
    integrity_status: str
    rebuild_warning: Any
    rebuild_invalid_seq: Any
    rebuild_observed_mismatch: Any


def build_failure_response(
    *,
    error_code: Any,
    reason: Any,
    tx_state: Any = None,
    recommended_next_tool: Any = None,
    recommended_action: Any = None,
    recoverable: Any = None,
    blocked: Any = None,
    integrity_status: Any = None,
    rebuild_warning: Any = None,
    rebuild_invalid_seq: Any = None,
    rebuild_observed_mismatch: Any = None,
    **extra_fields: Any,
) -> FailurePayload:
    resolved_error_code = _clean_str(error_code) or "invalid_ordering"
    defaults = _failure_defaults(resolved_error_code)

    response: FailurePayload = {
        "error_code": resolved_error_code,
        "reason": _clean_str(reason) or "workflow operation failed",
        "tx_state": tx_state,
        "recoverable": (
            _clean_bool(recoverable)
            if _clean_bool(recoverable) is not None
            else bool(defaults.get("recoverable", True))
        ),
        "blocked": (
            _clean_bool(blocked) if _clean_bool(blocked) is not None else False
        ),
        "recommended_next_tool": (
            _clean_str(recommended_next_tool)
            or _clean_str(defaults.get("recommended_next_tool"))
        ),
        "recommended_action": (
            _clean_str(recommended_action)
            or _clean_str(defaults.get("recommended_action"))
        ),
    }

    cleaned_integrity_status = _clean_optional_str(integrity_status)
    if cleaned_integrity_status:
        response["integrity_status"] = cleaned_integrity_status

    if rebuild_warning is not None:
        response["rebuild_warning"] = rebuild_warning
    if rebuild_invalid_seq is not None:
        response["rebuild_invalid_seq"] = rebuild_invalid_seq
    if rebuild_observed_mismatch is not None:
        response["rebuild_observed_mismatch"] = rebuild_observed_mismatch

    for key, value in extra_fields.items():
        response[key] = value

    return response


def derive_workflow_guidance(
    tx_state: Any,
    *,
    next_action_override: Any = None,
    phase_override: Any = None,
    requires_followup: Any = None,
    followup_tool: Any = None,
    terminal: Any = None,
    can_start_new_ticket: Any = None,
    resume_required: Any = None,
) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    active_tx = _active_tx_from_state(state)
    verify_state = _verify_state_from_state(state, active_tx)
    commit_state = _commit_state_from_state(state, active_tx)
    integrity = _resume_load_integrity(state)

    canonical_status = _clean_optional_str(state.get("status"))
    stored_next_action = _clean_optional_str(state.get("next_action"))

    if integrity.get("drift_detected") is True:
        canonical_phase = "blocked"
        next_action = "tx_state_rebuild"
        terminal_value = False
        requires_followup_value = True
        followup_tool_value = "tx_state_rebuild"
        can_start_new_ticket_value = False
        resume_required_value = False
    elif canonical_status in TERMINAL_STATUSES:
        canonical_phase = canonical_status
        next_action = stored_next_action or (
            "tx.begin" if canonical_status == "done" else "tx.end.blocked"
        )
        terminal_value = True
        requires_followup_value = False
        followup_tool_value = None
        can_start_new_ticket_value = canonical_status == "done"
        resume_required_value = False
    elif not active_tx:
        canonical_status = canonical_status
        canonical_phase = _clean_optional_str(phase_override)
        if not canonical_phase:
            canonical_phase = canonical_status or "idle"
        next_action = stored_next_action or "tx.begin"
        terminal_value = False
        requires_followup_value = next_action != "tx.begin"
        followup_tool_value = next_action if requires_followup_value else None
        can_start_new_ticket_value = next_action == "tx.begin"
        resume_required_value = False
    else:
        verify_status = _clean_optional_str(verify_state.get("status"))
        commit_status = _clean_optional_str(commit_state.get("status"))

        canonical_phase = (
            _clean_optional_str(phase_override)
            or commit_status
            or verify_status
            or canonical_status
            or "in-progress"
        )
        next_action = stored_next_action or "ops_update_task"
        terminal_value = False
        requires_followup_value = next_action not in {"", "tx.begin"}
        followup_tool_value = next_action if requires_followup_value else None
        can_start_new_ticket_value = False
        resume_required_value = True

    override_next_action = _clean_optional_str(next_action_override)
    if override_next_action:
        next_action = override_next_action

    override_phase = _clean_optional_str(phase_override)
    if override_phase:
        canonical_phase = override_phase

    if isinstance(terminal, bool):
        terminal_value = terminal
    if isinstance(requires_followup, bool):
        requires_followup_value = requires_followup
    if isinstance(can_start_new_ticket, bool):
        can_start_new_ticket_value = can_start_new_ticket
    if isinstance(resume_required, bool):
        resume_required_value = resume_required

    override_followup_tool = _clean_optional_str(followup_tool)
    if override_followup_tool:
        followup_tool_value = override_followup_tool
    elif requires_followup_value and not followup_tool_value:
        followup_tool_value = next_action
    elif not requires_followup_value:
        followup_tool_value = None

    return {
        "canonical_status": canonical_status,
        "canonical_phase": canonical_phase,
        "next_action": next_action,
        "terminal": terminal_value,
        "requires_followup": requires_followup_value,
        "followup_tool": followup_tool_value,
        "can_start_new_ticket": can_start_new_ticket_value,
        "resume_required": resume_required_value,
    }


def build_success_response(
    *,
    tx_state: Any,
    payload: Any = None,
    event: Any = None,
    **guidance_overrides: Any,
) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    guidance = derive_workflow_guidance(state, **guidance_overrides)
    active_tx = _active_tx_from_state(state)
    verify_state = _verify_state_from_state(state, active_tx)
    commit_state = _commit_state_from_state(state, active_tx)
    integrity = _resume_load_integrity(state)

    response: Dict[str, Any] = {
        "ok": True,
        "tx_state": state,
        "payload": payload,
        "event": event,
        "tx_status": guidance["canonical_status"],
        "tx_phase": guidance["canonical_phase"],
        "canonical_status": guidance["canonical_status"],
        "canonical_phase": guidance["canonical_phase"],
        "next_action": guidance["next_action"],
        "terminal": guidance["terminal"],
        "requires_followup": guidance["requires_followup"],
        "followup_tool": guidance["followup_tool"],
        "can_start_new_ticket": guidance["can_start_new_ticket"],
        "resume_required": guidance["resume_required"],
        "active_tx": active_tx or None,
        "active_tx_id": active_tx.get("tx_id") if active_tx else None,
        "active_ticket_id": active_tx.get("ticket_id") if active_tx else None,
        "current_step": None,
        "verify_status": verify_state.get("status"),
        "commit_status": commit_state.get("status"),
        "integrity_status": (
            "blocked" if integrity.get("drift_detected") is True else "healthy"
        ),
    }

    return response


class ResumeLoadFailureResult(TypedDict):
    ok: bool
    tx_state: Any
    failure: Optional[FailurePayload]
    return_baseline: bool
    outcome_kind: ResumeLoadFailureResultKind


ResumeLoadOutcomeKind: TypeAlias = Literal[
    "integrity_failure",
    "rebuilt_state",
    "incomplete_failure",
    "baseline",
    "malformed_rebuild_failure",
    "malformed_materialized_failure",
]
ResumeLoadFailureResultKind: TypeAlias = Literal[
    "materialized_state",
    "integrity_failure",
    "rebuilt_state",
    "incomplete_failure",
    "baseline",
    "malformed_rebuild_failure",
    "malformed_materialized_failure",
]


class ResumeLoadOutcome(TypedDict):
    kind: ResumeLoadOutcomeKind
    state: Any
    rebuild_requested: bool


ResumeLoadRaiseFailure: TypeAlias = Callable[[FailurePayload], None]
ResumeLoadFailureHandler: TypeAlias = Callable[[Any], Any]
ResumeLoadStateValidator: TypeAlias = Callable[[Any], bool]
ResumeLoadStateRebuilder: TypeAlias = Callable[[], Any]
ResumeLoadStateReader: TypeAlias = Callable[[], Any]
ResumeLoadSharedReturn: TypeAlias = Any
ResumeLoadFailureAdapterMap: TypeAlias = Dict[str, ResumeLoadFailureHandler]


# Resume-load result builders


def _resume_load_success_result(
    *,
    tx_state: Any,
    outcome_kind: ResumeLoadFailureResultKind,
) -> ResumeLoadFailureResult:
    return {
        "ok": True,
        "tx_state": tx_state,
        "failure": None,
        "return_baseline": False,
        "outcome_kind": outcome_kind,
    }


def _resume_load_baseline_result(
    *,
    tx_state: Any,
    promote_to_success: bool,
) -> ResumeLoadFailureResult:
    return {
        "ok": bool(promote_to_success),
        "tx_state": tx_state,
        "failure": None,
        "return_baseline": not bool(promote_to_success),
        "outcome_kind": "baseline",
    }


def _resume_load_failure_result(
    *,
    failure: FailurePayload,
    outcome_kind: ResumeLoadFailureResultKind,
) -> ResumeLoadFailureResult:
    return {
        "ok": False,
        "tx_state": None,
        "failure": failure,
        "return_baseline": False,
        "outcome_kind": outcome_kind,
    }


# Resume-load failure dispatch


def _resume_load_dispatch_failure(
    *,
    result: ResumeLoadFailureResult,
    tx_state: Any,
    on_integrity_failure: ResumeLoadFailureHandler,
    on_incomplete_failure: ResumeLoadFailureHandler,
    on_rebuild_malformed_failure: ResumeLoadFailureHandler,
    on_materialized_malformed_failure: ResumeLoadFailureHandler,
) -> ResumeLoadSharedReturn:
    failure = result["failure"]
    if not isinstance(failure, dict):
        return result["tx_state"]

    outcome_kind = result.get("outcome_kind")

    if outcome_kind == "integrity_failure":
        return on_integrity_failure(failure.get("tx_state") or tx_state)
    if outcome_kind == "incomplete_failure":
        return on_incomplete_failure(failure.get("tx_state") or tx_state)
    if outcome_kind == "malformed_rebuild_failure":
        return on_rebuild_malformed_failure(failure.get("tx_state"))
    return on_materialized_malformed_failure(failure.get("tx_state"))


# Resume-load raise helpers


def _resume_load_raise_integrity_failure(
    *,
    raise_failure: ResumeLoadRaiseFailure,
    state: Any,
    recommended_action: Any,
) -> None:
    raise_failure(
        build_resume_load_integrity_failure(
            tx_state=state,
            recommended_action=recommended_action,
        )
    )


def _resume_load_raise_incomplete_failure(
    *,
    raise_failure: ResumeLoadRaiseFailure,
    state: Any,
    recommended_action: Any,
) -> None:
    raise_failure(
        build_resume_load_incomplete_failure(
            tx_state=state,
            recommended_action=recommended_action,
        )
    )


def _resume_load_raise_rebuild_malformed_failure(
    *,
    raise_failure: ResumeLoadRaiseFailure,
    tx_state: Any,
    recommended_action: Any,
) -> None:
    raise_failure(
        build_resume_load_malformed_failure(
            tx_state=tx_state,
            recommended_next_tool="tx_state_rebuild",
            recommended_action=recommended_action,
            reason="resume blocked by malformed canonical persistence",
        )
    )


def _resume_load_raise_materialized_malformed_failure(
    *,
    raise_failure: ResumeLoadRaiseFailure,
    tx_state: Any,
    recommended_action: Any,
) -> None:
    raise_failure(
        build_resume_load_malformed_failure(
            tx_state=tx_state,
            recommended_next_tool="ops_capture_state",
            recommended_action=recommended_action,
            reason="resume blocked because materialized canonical state is malformed",
        )
    )


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


def canonical_idle_baseline(
    *, include_integrity: bool = True, integrity: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    baseline = dict(CANONICAL_IDLE_BASELINE)
    if include_integrity:
        baseline["integrity"] = dict(integrity) if isinstance(integrity, dict) else {}
    return baseline


def _materialized_state_dict(tx_state: Any) -> Dict[str, Any]:
    if isinstance(tx_state, dict):
        return tx_state
    return {}


def _materialized_active_tx_dict(tx_state: Any) -> Optional[Dict[str, Any]]:
    state = _materialized_state_dict(tx_state)
    active_tx = state.get("active_tx")
    if isinstance(active_tx, dict):
        return active_tx
    return None


def _is_strict_idle_baseline_state(tx_state: Any) -> bool:
    state = _materialized_state_dict(tx_state)
    if not state:
        return False
    return (
        state.get("active_tx") is None
        and state.get("status") is None
        and state.get("next_action") == "tx.begin"
        and state.get("verify_state") is None
        and state.get("commit_state") is None
        and state.get("semantic_summary") is None
    )


def _is_valid_exact_active_resume_state(tx_state: Any) -> bool:
    state = _materialized_state_dict(tx_state)
    if not state:
        return False

    active_tx = _materialized_active_tx_dict(state)
    if not isinstance(active_tx, dict):
        return False

    tx_id = active_tx.get("tx_id")
    ticket_id = active_tx.get("ticket_id")
    status = state.get("status")
    next_action = state.get("next_action")

    return (
        isinstance(tx_id, int)
        and not isinstance(tx_id, bool)
        and isinstance(ticket_id, str)
        and bool(ticket_id.strip())
        and isinstance(status, str)
        and bool(status.strip())
        and status.strip() not in TERMINAL_STATUSES
        and isinstance(next_action, str)
        and bool(next_action.strip())
    )


def is_valid_exact_resume_tx_state(tx_state: Any) -> bool:
    return _is_strict_idle_baseline_state(
        tx_state
    ) or _is_valid_exact_active_resume_state(tx_state)


def requests_resume_state_rebuild(tx_state: Any) -> bool:
    if tx_state is None:
        return True
    if _is_strict_idle_baseline_state(tx_state):
        return False
    return not is_valid_exact_resume_tx_state(tx_state)


# Resume-load internals


def _resume_load_integrity(tx_state: Any) -> Dict[str, Any]:
    state = _as_dict(tx_state)
    integrity = state.get("integrity")
    return dict(integrity) if isinstance(integrity, dict) else {}


def _resume_load_materialized_state(tx_state: Any) -> Dict[str, Any]:
    return tx_state if isinstance(tx_state, dict) else {}


def _resume_load_rebuilt_state(rebuild: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(rebuild, dict):
        return None
    state = rebuild.get("state")
    return state if isinstance(state, dict) else None


def _resume_load_outcome(
    *,
    tx_state: Any,
    rebuilt_state: Any,
    is_valid_state: ResumeLoadStateValidator,
    baseline: Optional[Dict[str, Any]] = None,
) -> ResumeLoadOutcome:
    materialized_state = _resume_load_materialized_state(tx_state)
    rebuild_requested = requests_resume_state_rebuild(tx_state)

    if isinstance(rebuilt_state, dict):
        integrity = _resume_load_integrity(rebuilt_state)
        if integrity.get("drift_detected") is True:
            return {
                "kind": "integrity_failure",
                "state": rebuilt_state,
                "rebuild_requested": rebuild_requested,
            }
        if is_valid_state(rebuilt_state):
            return {
                "kind": "rebuilt_state",
                "state": rebuilt_state,
                "rebuild_requested": rebuild_requested,
            }
        return {
            "kind": "incomplete_failure",
            "state": rebuilt_state,
            "rebuild_requested": rebuild_requested,
        }

    if tx_state is None:
        return {
            "kind": "baseline",
            "state": dict(baseline)
            if isinstance(baseline, dict)
            else canonical_idle_baseline(),
            "rebuild_requested": rebuild_requested,
        }

    if rebuild_requested:
        return {
            "kind": "malformed_rebuild_failure",
            "state": materialized_state or None,
            "rebuild_requested": rebuild_requested,
        }

    return {
        "kind": "malformed_materialized_failure",
        "state": materialized_state or None,
        "rebuild_requested": rebuild_requested,
    }


def _resume_load_failure_kind(
    outcome: Mapping[str, Any],
) -> Optional[ResumeLoadOutcomeKind]:
    kind = outcome.get("kind")
    return kind if isinstance(kind, str) and kind.strip() else None


# Resume-load failure payload builders
#
# Keep these ordered generic -> specific:
# integrity drift, incomplete rebuilt state, then malformed-state variants.


def _build_resume_load_integrity_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair the invalid canonical history before resuming the exact active "
        "transaction."
    ),
    reason: Any = "resume blocked by ambiguous canonical persistence",
    blocked: bool = True,
    **guidance_overrides: Any,
) -> FailurePayload:
    rebuilt_state = _as_dict(tx_state)
    return build_failure_response(
        error_code="integrity_blocked",
        reason=reason,
        tx_state=rebuilt_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        recoverable=False,
        blocked=blocked,
        rebuild_warning=rebuilt_state.get("rebuild_warning"),
        rebuild_invalid_seq=rebuilt_state.get("rebuild_invalid_seq"),
        rebuild_observed_mismatch=rebuilt_state.get("rebuild_observed_mismatch"),
        **guidance_overrides,
    )


def _build_resume_load_incomplete_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active "
        "transaction state with top-level next_action."
    ),
    reason: Any = "resume blocked because rebuilt canonical state is incomplete",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_resume_load_malformed_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any,
    recommended_action: Any,
    reason: Any,
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


# Resume-load public failure builders


def build_resume_load_integrity_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair the invalid canonical history before resuming the exact active "
        "transaction."
    ),
    reason: Any = "resume blocked by ambiguous canonical persistence",
    blocked: bool = True,
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_resume_load_integrity_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        blocked=blocked,
        **guidance_overrides,
    )


def build_resume_load_incomplete_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active "
        "transaction state with top-level next_action."
    ),
    reason: Any = "resume blocked because rebuilt canonical state is incomplete",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_resume_load_incomplete_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_resume_load_malformed_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any,
    recommended_action: Any,
    reason: Any,
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_resume_load_malformed_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


# Resume-load adapter builders


def raise_runtime_error(payload: Dict[str, Any]) -> None:
    raise RuntimeError(payload)


def raise_value_error_json(payload: Dict[str, Any]) -> None:
    raise ValueError(json.dumps(payload, ensure_ascii=False))


def build_resume_load_raise_adapter(
    *,
    raise_failure: ResumeLoadRaiseFailure,
    integrity_failure_action: Any = (
        "Repair the invalid canonical history before resuming the exact active "
        "transaction."
    ),
    incomplete_failure_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active "
        "transaction state with top-level next_action."
    ),
    rebuild_malformed_action: Any = (
        "Repair malformed canonical persistence before resuming the exact active "
        "transaction."
    ),
    materialized_malformed_action: Any = (
        "Restore canonical top-level status and next_action before resuming the "
        "exact active transaction."
    ),
) -> ResumeLoadFailureAdapterMap:
    return {
        "on_integrity_failure": lambda state: _resume_load_raise_integrity_failure(
            raise_failure=raise_failure,
            state=state,
            recommended_action=integrity_failure_action,
        ),
        "on_incomplete_failure": lambda state: _resume_load_raise_incomplete_failure(
            raise_failure=raise_failure,
            state=state,
            recommended_action=incomplete_failure_action,
        ),
        "on_rebuild_malformed_failure": (
            lambda tx_state: _resume_load_raise_rebuild_malformed_failure(
                raise_failure=raise_failure,
                tx_state=tx_state,
                recommended_action=rebuild_malformed_action,
            )
        ),
        "on_materialized_malformed_failure": (
            lambda tx_state: _resume_load_raise_materialized_malformed_failure(
                raise_failure=raise_failure,
                tx_state=tx_state,
                recommended_action=materialized_malformed_action,
            )
        ),
    }


def build_resume_load_runtime_error_adapter(
    *,
    integrity_failure_action: Any = (
        "Repair the invalid canonical history before resuming the exact active "
        "transaction."
    ),
    incomplete_failure_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active "
        "transaction state with top-level next_action."
    ),
    rebuild_malformed_action: Any = (
        "Repair malformed canonical persistence before resuming the exact active "
        "transaction."
    ),
    materialized_malformed_action: Any = (
        "Restore canonical top-level status and next_action before resuming the "
        "exact active transaction."
    ),
) -> ResumeLoadFailureAdapterMap:
    return build_resume_load_raise_adapter(
        raise_failure=raise_runtime_error,
        integrity_failure_action=integrity_failure_action,
        incomplete_failure_action=incomplete_failure_action,
        rebuild_malformed_action=rebuild_malformed_action,
        materialized_malformed_action=materialized_malformed_action,
    )


def build_resume_load_value_error_adapter(
    *,
    integrity_failure_action: Any = (
        "Repair the invalid canonical history before resuming the exact active "
        "transaction."
    ),
    incomplete_failure_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active "
        "transaction state with top-level next_action."
    ),
    rebuild_malformed_action: Any = (
        "Repair malformed canonical persistence before resuming the exact active "
        "transaction."
    ),
    materialized_malformed_action: Any = (
        "Restore canonical top-level status and next_action before resuming the "
        "exact active transaction."
    ),
) -> ResumeLoadFailureAdapterMap:
    return build_resume_load_raise_adapter(
        raise_failure=raise_value_error_json,
        integrity_failure_action=integrity_failure_action,
        incomplete_failure_action=incomplete_failure_action,
        rebuild_malformed_action=rebuild_malformed_action,
        materialized_malformed_action=materialized_malformed_action,
    )


# Resume-load public helpers


def build_resume_load_failure(
    *,
    tx_state: Any,
    is_valid_tx_state: ResumeLoadStateValidator,
    rebuild_tx_state: ResumeLoadStateRebuilder,
    baseline: Optional[Dict[str, Any]] = None,
    promote_baseline_to_success: bool = False,
    integrity_failure_action: Any = (
        "Repair the invalid canonical history before resuming the exact active transaction."
    ),
    incomplete_failure_action: Any = (
        "Repair canonical persistence so rebuild yields a complete exact active transaction state with top-level next_action."
    ),
    rebuild_malformed_action: Any = (
        "Repair malformed canonical persistence before resuming the exact active transaction."
    ),
    materialized_malformed_action: Any = (
        "Restore canonical top-level status and next_action before resuming the exact active transaction."
    ),
) -> ResumeLoadFailureResult:
    if is_valid_tx_state(tx_state):
        return _resume_load_success_result(
            tx_state=tx_state,
            outcome_kind="materialized_state",
        )

    rebuild = rebuild_tx_state()
    rebuilt_state = _resume_load_rebuilt_state(rebuild)
    outcome = _resume_load_outcome(
        tx_state=tx_state,
        rebuilt_state=rebuilt_state,
        is_valid_state=is_valid_tx_state,
        baseline=baseline,
    )

    kind = _resume_load_failure_kind(outcome)
    state = outcome["state"]

    if kind == "rebuilt_state":
        return _resume_load_success_result(
            tx_state=state,
            outcome_kind=kind,
        )

    if kind == "baseline":
        return _resume_load_baseline_result(
            tx_state=state,
            promote_to_success=promote_baseline_to_success,
        )

    if kind == "integrity_failure":
        failure = build_resume_load_integrity_failure(
            tx_state=state,
            recommended_action=integrity_failure_action,
        )
    elif kind == "incomplete_failure":
        failure = build_resume_load_incomplete_failure(
            tx_state=state,
            recommended_action=incomplete_failure_action,
        )
    elif kind == "malformed_rebuild_failure":
        failure = build_resume_load_malformed_failure(
            tx_state=state,
            recommended_next_tool="tx_state_rebuild",
            recommended_action=rebuild_malformed_action,
            reason="resume blocked by malformed canonical persistence",
        )
    else:
        failure = build_resume_load_malformed_failure(
            tx_state=state,
            recommended_next_tool="ops_capture_state",
            recommended_action=materialized_malformed_action,
            reason="resume blocked because materialized canonical state is malformed",
        )

    return _resume_load_failure_result(
        failure=failure,
        outcome_kind=kind or "malformed_materialized_failure",
    )


def load_resume_state_shared(
    *,
    read_tx_state: ResumeLoadStateReader,
    rebuild_tx_state: ResumeLoadStateRebuilder,
    is_valid_tx_state: ResumeLoadStateValidator,
    on_integrity_failure: ResumeLoadFailureHandler,
    on_incomplete_failure: ResumeLoadFailureHandler,
    on_rebuild_malformed_failure: ResumeLoadFailureHandler,
    on_materialized_malformed_failure: ResumeLoadFailureHandler,
    baseline: Dict[str, Any],
    rebuild_when_invalid: bool,
) -> ResumeLoadSharedReturn:
    tx_state = read_tx_state()
    if tx_state is None:
        return (
            dict(baseline) if isinstance(baseline, dict) else canonical_idle_baseline()
        )

    result = build_resume_load_failure(
        tx_state=tx_state,
        is_valid_tx_state=is_valid_tx_state,
        rebuild_tx_state=(
            rebuild_tx_state if rebuild_when_invalid else lambda: {"ok": False}
        ),
        baseline=baseline,
        promote_baseline_to_success=True,
    )

    if result["ok"]:
        return result["tx_state"]

    return _resume_load_dispatch_failure(
        result=result,
        tx_state=tx_state,
        on_integrity_failure=on_integrity_failure,
        on_incomplete_failure=on_incomplete_failure,
        on_rebuild_malformed_failure=on_rebuild_malformed_failure,
        on_materialized_malformed_failure=on_materialized_malformed_failure,
    )


# Helper-bootstrap failure payload builders
#
# Keep these grouped from the generic invalid-resume payload to the more
# specific integrity-drift payload.


def _build_bootstrap_invalid_resume_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair canonical persistence so helper bootstrap resumes only from a "
        "valid exact active transaction state."
    ),
    reason: Any = (
        "helper bootstrap blocked because rebuilt canonical state is not a "
        "valid exact-resume snapshot"
    ),
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_bootstrap_integrity_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair the invalid canonical history before allowing helper bootstrap "
        "to emit tx.begin."
    ),
    reason: Any = "helper bootstrap blocked by canonical integrity drift",
    blocked: bool = True,
    **guidance_overrides: Any,
) -> FailurePayload:
    rebuilt_state = _as_dict(tx_state)
    return build_failure_response(
        error_code="integrity_blocked",
        reason=reason,
        tx_state=rebuilt_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        recoverable=False,
        blocked=blocked,
        rebuild_warning=rebuilt_state.get("rebuild_warning"),
        rebuild_invalid_seq=rebuilt_state.get("rebuild_invalid_seq"),
        rebuild_observed_mismatch=rebuilt_state.get("rebuild_observed_mismatch"),
        **guidance_overrides,
    )


# Helper-bootstrap public failure builders


def build_bootstrap_invalid_resume_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair canonical persistence so helper bootstrap resumes only from a "
        "valid exact active transaction state."
    ),
    reason: Any = (
        "helper bootstrap blocked because rebuilt canonical state is not a "
        "valid exact-resume snapshot"
    ),
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_bootstrap_invalid_resume_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_bootstrap_integrity_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "tx_state_rebuild",
    recommended_action: Any = (
        "Repair the invalid canonical history before allowing helper bootstrap "
        "to emit tx.begin."
    ),
    reason: Any = "helper bootstrap blocked by canonical integrity drift",
    blocked: bool = True,
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_bootstrap_integrity_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        blocked=blocked,
        **guidance_overrides,
    )


# Verify-start failure payload builders
#
# Keep these grouped generic -> specific:
# missing state, missing active transaction, lifecycle prerequisite,
# resumability/next-action details, then persistence failure.


def _build_verify_start_missing_tx_state_failure_payload(
    *,
    tx_state: Any = None,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Ensure canonical transaction state is materialized before returning "
        "verify results."
    ),
    reason: Any = "verify.start not recorded; tx_state missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_verify_start_missing_active_tx_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Restore the exact active transaction state before returning verify results."
    ),
    reason: Any = "verify.start not recorded; active_tx missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_verify_start_begin_required_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_start_task",
    recommended_action: Any = (
        "Start or resume the canonical transaction before returning verify results."
    ),
    reason: Any = "verify.start not recorded; tx.begin required before verify results",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="begin_required",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_verify_start_not_resumable_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_update_task",
    recommended_action: Any = (
        "Resume the exact active non-terminal transaction before returning "
        "verify results."
    ),
    reason: Any = "verify.start not recorded; active transaction is not resumable",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_verify_start_missing_next_action_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_update_task",
    recommended_action: Any = (
        "Restore the exact active transaction with a valid top-level "
        "next_action before returning verify results."
    ),
    reason: Any = "verify.start not recorded; canonical next_action missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_verify_start_not_persisted_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Repair state persistence so verify.start updates canonical verify_state "
        "before continuing."
    ),
    reason: Any = "verify.start emitted but tx_state was not updated to running",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


# Verify-start public failure builders


def build_verify_start_missing_tx_state_failure(
    *,
    tx_state: Any = None,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Ensure canonical transaction state is materialized before returning "
        "verify results."
    ),
    reason: Any = "verify.start not recorded; tx_state missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_missing_tx_state_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_verify_start_missing_active_tx_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Restore the exact active transaction state before returning verify results."
    ),
    reason: Any = "verify.start not recorded; active_tx missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_missing_active_tx_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_verify_start_begin_required_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_start_task",
    recommended_action: Any = (
        "Start or resume the canonical transaction before returning verify results."
    ),
    reason: Any = "verify.start not recorded; tx.begin required before verify results",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_begin_required_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_verify_start_not_resumable_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_update_task",
    recommended_action: Any = (
        "Resume the exact active non-terminal transaction before returning "
        "verify results."
    ),
    reason: Any = "verify.start not recorded; active transaction is not resumable",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_not_resumable_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_verify_start_missing_next_action_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_update_task",
    recommended_action: Any = (
        "Restore the exact active transaction with a valid top-level "
        "next_action before returning verify results."
    ),
    reason: Any = "verify.start not recorded; canonical next_action missing",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_missing_next_action_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_verify_start_not_persisted_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Repair state persistence so verify.start updates canonical verify_state "
        "before continuing."
    ),
    reason: Any = "verify.start emitted but tx_state was not updated to running",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_verify_start_not_persisted_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


# Commit-helper failure payload builders
#
# Keep these grouped from verification prerequisite failure to post-verify
# no-op commit rejection.


def _build_commit_verify_failed_failure_payload(
    *,
    tx_state: Any,
    reason: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Repair the verification failure and rerun verification before "
        "attempting commit."
    ),
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="verify_failed",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_commit_no_changes_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_end_task",
    recommended_action: Any = (
        "If work is already verified and nothing remains to commit, close the "
        "transaction explicitly or make additional changes before retrying commit."
    ),
    reason: Any = "no changes to commit",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def _build_commit_no_files_failure_payload(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_commit",
    recommended_action: Any = (
        "Provide one or more files or use auto staging before retrying commit."
    ),
    reason: Any = "no files specified",
    **guidance_overrides: Any,
) -> FailurePayload:
    return build_failure_response(
        error_code="invalid_ordering",
        reason=reason,
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


# Commit-helper public failure builders


def build_commit_verify_failed_failure(
    *,
    tx_state: Any,
    reason: Any,
    recommended_next_tool: Any = "repo_verify",
    recommended_action: Any = (
        "Repair the verification failure and rerun verification before "
        "attempting commit."
    ),
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_commit_verify_failed_failure_payload(
        tx_state=tx_state,
        reason=reason,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        **guidance_overrides,
    )


def build_commit_no_changes_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "ops_end_task",
    recommended_action: Any = (
        "If work is already verified and nothing remains to commit, close the "
        "transaction explicitly or make additional changes before retrying commit."
    ),
    reason: Any = "no changes to commit",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_commit_no_changes_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )


def build_commit_no_files_failure(
    *,
    tx_state: Any,
    recommended_next_tool: Any = "repo_commit",
    recommended_action: Any = (
        "Provide one or more files or use auto staging before retrying commit."
    ),
    reason: Any = "no files specified",
    **guidance_overrides: Any,
) -> FailurePayload:
    return _build_commit_no_files_failure_payload(
        tx_state=tx_state,
        recommended_next_tool=recommended_next_tool,
        recommended_action=recommended_action,
        reason=reason,
        **guidance_overrides,
    )
