import json

import pytest


def _append_tx_event(state_store, **overrides):
    base = {
        "tx_id": "tx-1",
        "ticket_id": "p4-t2",
        "event_type": "tx.begin",
        "phase": "in-progress",
        "step_id": "p4-t2-s1",
        "actor": {"agent_id": "a1"},
        "session_id": "s1",
        "payload": {"ticket_id": "p4-t2", "ticket_title": "p4-t2"},
    }
    base.update(overrides)
    return state_store.tx_event_append(**base)


def _append_raw_tx_event(repo_context, event):
    with repo_context.tx_event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def test_read_tx_event_log_filters_seq(repo_context, state_store, state_rebuilder):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )

    events = state_rebuilder.read_tx_event_log(start_seq=1)
    assert [event["seq"] for event in events["events"]] == [2]

    events = state_rebuilder.read_tx_event_log(start_seq=0, end_seq=1)
    assert [event["seq"] for event in events["events"]] == [1]


def test_read_tx_event_log_handles_invalid_lines(repo_context, state_rebuilder):
    repo_context.tx_event_log.parent.mkdir(parents=True, exist_ok=True)
    repo_context.tx_event_log.write_text(
        "\n".join(
            [
                "{bad json",
                json.dumps(["not", "a", "dict"]),
                json.dumps({"seq": "nope"}),
                json.dumps({"seq": 1, "tx_id": "t", "ticket_id": "x"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = state_rebuilder.read_tx_event_log(start_seq=0)
    assert result["invalid_lines"] == 3
    assert [event["seq"] for event in result["events"]] == [1]


def test_read_recent_tx_events_returns_tail(repo_context, state_store, state_rebuilder):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s2",
        payload={"step_id": "p4-t2-s2", "description": "step"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s3",
        payload={"step_id": "p4-t2-s3", "description": "step"},
    )

    events = state_rebuilder.read_recent_tx_events(2)
    assert [event["seq"] for event in events] == [2, 3]


def test_rebuild_tx_state_uses_materialized_when_intact(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    state_store.tx_state_save(rebuild["state"])

    rebuild_again = state_rebuilder.rebuild_tx_state()
    assert rebuild_again["ok"] is True
    assert rebuild_again["source"] == "materialized"


def test_rebuild_tx_state_reconstructs_file_intent_next_action(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.step.enter",
        step_id="p4-t2-s1",
        payload={"step_id": "p4-t2-s1", "description": "step"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.add",
        payload={
            "path": "a.py",
            "operation": "update",
            "purpose": "update tests",
            "planned_step": "p4-t2-s1",
            "state": "planned",
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["next_action"] == "continue file intents"


def test_rebuild_tx_state_committed_next_action(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.verify.start",
        phase="checking",
        payload={"command": "verify"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.verify.pass",
        phase="verified",
        payload={"ok": True, "returncode": 0, "summary": "ok"},
    )
    _append_tx_event(
        state_store,
        event_type="tx.commit.start",
        phase="verified",
        payload={
            "message": "commit",
            "files": "auto",
            "branch": "main",
            "diff_summary": "diff",
        },
    )
    _append_tx_event(
        state_store,
        event_type="tx.commit.done",
        phase="committed",
        payload={
            "sha": "abc123",
            "summary": "done",
            "branch": "main",
            "diff_summary": "diff",
        },
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["status"] == "committed"
    assert active_tx["next_action"] == "tx.end.done"


def test_rebuild_tx_state_torn_event_truncates(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_raw_tx_event(
        repo_context, {"seq": 2, "event_id": "evt-bad", "tx_id": "tx-1"}
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_missing_file_intent_truncates(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.file_intent.update",
        payload={"path": "missing.py", "state": "started"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    assert rebuild["last_applied_seq"] == 1


def test_rebuild_tx_state_preserves_user_intent(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)
    _append_tx_event(
        state_store,
        event_type="tx.user_intent.set",
        payload={"user_intent": "continue"},
    )

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert active_tx["user_intent"] == "continue"


def test_rebuild_tx_state_semantic_summary_fallback(
    repo_context, state_store, state_rebuilder
):
    _append_tx_event(state_store)

    rebuild = state_rebuilder.rebuild_tx_state()
    assert rebuild["ok"] is True
    active_tx = rebuild["state"]["active_tx"]
    assert isinstance(active_tx["semantic_summary"], str)
    assert active_tx["semantic_summary"]
