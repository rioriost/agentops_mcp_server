#!/usr/bin/env python3
"""
Minimal MCP-like stdio server.

This implements a tiny JSON-RPC 2.0 protocol over stdin/stdout to expose tools.
It is intentionally lightweight and dependency-free so you can adapt it to your
preferred MCP client integration.

Supported methods:
- tools/list -> returns tool schemas
- tools/call -> invokes a tool by name with arguments

Tools (snake_case):
- commit_if_verified(message, timeout_sec?) -> run verify and commit changes
- journal_append(kind, payload, session_id?, agent_id?, event_id?) -> append event
- snapshot_save(state, session_id?, last_applied_seq?, snapshot_id?) -> save snapshot
- snapshot_load() -> load snapshot
- checkpoint_update(last_applied_seq, snapshot_path?, checkpoint_id?) -> update checkpoint
- checkpoint_read() -> read checkpoint
- roll_forward_replay(checkpoint_path?, snapshot_path?, start_seq?, end_seq?) -> replay journal
- continue_state_rebuild(checkpoint_path?, snapshot_path?, start_seq?, end_seq?, session_id?) -> rebuild state
- repo_verify(timeout_sec?) -> run verify script
- repo_commit(message?, files="auto") -> commit changes
- repo_status_summary() -> summarize repo status and diff
- repo_commit_message_suggest(diff?) -> suggest commit messages
- session_capture_context(run_verify?, log?) -> capture repo context
- tests_suggest(diff?, failures?) -> suggest tests
- tests_suggest_from_failures(log_path) -> suggest tests from failure logs
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _set_repo_root(root: Path) -> None:
    global REPO_ROOT, JOURNAL, SNAPSHOT, CHECKPOINT, VERIFY
    REPO_ROOT = root
    JOURNAL = REPO_ROOT / ".agent" / "journal.jsonl"
    SNAPSHOT = REPO_ROOT / ".agent" / "snapshot.json"
    CHECKPOINT = REPO_ROOT / ".agent" / "checkpoint.json"
    VERIFY = REPO_ROOT / ".zed" / "scripts" / "verify"


_set_repo_root(Path.cwd().resolve())


CODE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".cs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, content: str) -> None:
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def _read_last_json_line(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    return None


def _next_journal_seq() -> int:
    last = _read_last_json_line(JOURNAL)
    if isinstance(last, dict):
        seq = last.get("seq")
        if isinstance(seq, int) and seq >= 0:
            return seq + 1
    return 1


def journal_append(
    kind: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not kind:
        raise ValueError("kind is required")
    seq = _next_journal_seq()
    resolved_event_id = event_id or str(uuid.uuid4())
    rec: Dict[str, Any] = {
        "seq": seq,
        "event_id": resolved_event_id,
        "ts": _now_iso(),
        "project_root": str(REPO_ROOT),
        "kind": kind,
        "payload": payload,
    }
    if session_id is not None:
        rec["session_id"] = session_id
    if agent_id is not None:
        rec["agent_id"] = agent_id
    _ensure_parent(JOURNAL)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "seq": seq, "event_id": resolved_event_id}


def _truncate_text(value: Optional[str], limit: int = 2000) -> Optional[str]:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "...(truncated)"


def _sanitize_args(args: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not args:
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            sanitized[key] = _truncate_text(value)
        else:
            sanitized[key] = value
    return sanitized


def _summarize_result(result: Any, limit: int = 2000) -> Any:
    try:
        text = json.dumps(result, ensure_ascii=False)
    except TypeError:
        text = str(result)
    if len(text) <= limit:
        return result
    return {"summary": text[:limit].rstrip() + "...(truncated)", "truncated": True}


def _journal_safe(kind: str, payload: Dict[str, Any]) -> None:
    try:
        journal_append(kind=kind, payload=payload)
    except Exception:  # noqa: BLE001
        return


def _read_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_iso_ts(value: str) -> Optional[datetime]:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _week_start_utc(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    start = dt - timedelta(days=dt.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _read_first_event_with_ts(
    path: Path,
) -> Optional[Tuple[Dict[str, Any], datetime]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            ts_value = rec.get("ts")
            if not isinstance(ts_value, str):
                continue
            parsed = _parse_iso_ts(ts_value)
            if parsed is None:
                continue
            return rec, parsed
    return None


def _rotate_journal_if_prev_week() -> Dict[str, Any]:
    if not JOURNAL.exists():
        return {"ok": False, "reason": "journal not found", "path": str(JOURNAL)}
    first = _read_first_event_with_ts(JOURNAL)
    if not first:
        return {"ok": False, "reason": "no valid journal timestamps"}
    _, first_dt = first
    current_week = _week_start_utc(datetime.now(timezone.utc))
    first_week = _week_start_utc(first_dt)
    if first_week == current_week:
        return {"ok": True, "rotated": False, "reason": "current week only"}

    last_week_start = current_week - timedelta(days=7)
    last_week_end = current_week - timedelta(seconds=1)

    old_lines: List[str] = []
    keep_lines: List[str] = []
    invalid_json_lines = 0
    invalid_ts = 0

    with JOURNAL.open("r", encoding="utf-8") as f:
        for raw_line in f:
            if not raw_line.strip():
                continue
            try:
                rec = json.loads(raw_line)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                keep_lines.append(raw_line)
                continue
            if not isinstance(rec, dict):
                invalid_json_lines += 1
                keep_lines.append(raw_line)
                continue
            ts_value = rec.get("ts")
            if not isinstance(ts_value, str):
                invalid_ts += 1
                keep_lines.append(raw_line)
                continue
            parsed = _parse_iso_ts(ts_value)
            if parsed is None:
                invalid_ts += 1
                keep_lines.append(raw_line)
                continue
            serialized = json.dumps(rec, ensure_ascii=False) + "\n"
            if last_week_start <= parsed <= last_week_end:
                old_lines.append(serialized)
            else:
                keep_lines.append(serialized)

    if not old_lines:
        return {
            "ok": True,
            "rotated": False,
            "reason": "no last-week events",
            "invalid_json_lines": invalid_json_lines,
            "invalid_ts": invalid_ts,
        }

    archive = JOURNAL.with_name(
        f"journal.{last_week_start:%Y%m%d}-{last_week_end:%Y%m%d}.jsonl"
    )
    _write_text(archive, "".join(old_lines))
    _write_text(JOURNAL, "".join(keep_lines))
    return {
        "ok": True,
        "rotated": True,
        "archive": str(archive),
        "archived": len(old_lines),
        "kept": len(keep_lines),
        "invalid_json_lines": invalid_json_lines,
        "invalid_ts": invalid_ts,
    }


def snapshot_save(
    state: Dict[str, Any],
    session_id: Optional[str] = None,
    last_applied_seq: Optional[int] = None,
    snapshot_id: Optional[str] = None,
) -> Dict[str, Any]:
    if state is None:
        raise ValueError("state is required")
    resolved_snapshot_id = snapshot_id or str(uuid.uuid4())
    snapshot: Dict[str, Any] = {
        "snapshot_id": resolved_snapshot_id,
        "ts": _now_iso(),
        "project_root": str(REPO_ROOT),
        "state": state,
    }
    if session_id is not None:
        snapshot["session_id"] = session_id
    if last_applied_seq is not None:
        snapshot["last_applied_seq"] = last_applied_seq
    _write_text(SNAPSHOT, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "path": str(SNAPSHOT), "snapshot_id": resolved_snapshot_id}


def snapshot_load() -> Dict[str, Any]:
    snapshot = _read_json_file(SNAPSHOT)
    if snapshot is None:
        return {"ok": False, "reason": "snapshot not found", "path": str(SNAPSHOT)}
    return {"ok": True, "snapshot": snapshot, "path": str(SNAPSHOT)}


def checkpoint_update(
    last_applied_seq: int,
    snapshot_path: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    if last_applied_seq is None:
        raise ValueError("last_applied_seq is required")
    resolved_checkpoint_id = checkpoint_id or str(uuid.uuid4())
    snapshot_ref = snapshot_path or SNAPSHOT.name
    checkpoint: Dict[str, Any] = {
        "checkpoint_id": resolved_checkpoint_id,
        "ts": _now_iso(),
        "project_root": str(REPO_ROOT),
        "last_applied_seq": last_applied_seq,
        "snapshot_path": snapshot_ref,
    }
    _write_text(CHECKPOINT, json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n")
    return {
        "ok": True,
        "path": str(CHECKPOINT),
        "checkpoint_id": resolved_checkpoint_id,
    }


def checkpoint_read() -> Dict[str, Any]:
    checkpoint = _read_json_file(CHECKPOINT)
    if checkpoint is None:
        return {"ok": False, "reason": "checkpoint not found", "path": str(CHECKPOINT)}
    return {"ok": True, "checkpoint": checkpoint, "path": str(CHECKPOINT)}


def _resolve_path(path_value: Optional[str], default: Path) -> Path:
    if path_value is None:
        return default
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return REPO_ROOT / candidate


def _read_journal_events(
    start_seq: int,
    end_seq: Optional[int] = None,
    journal_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if start_seq < 0:
        raise ValueError("start_seq must be >= 0")
    if end_seq is not None and end_seq < start_seq:
        raise ValueError("end_seq must be >= start_seq")

    path = journal_path or JOURNAL
    events: List[Dict[str, Any]] = []
    invalid_lines = 0
    last_seq = start_seq

    if not path.exists():
        return {
            "events": events,
            "invalid_lines": invalid_lines,
            "last_seq": last_seq,
            "path": str(path),
        }

    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if not isinstance(rec, dict):
                invalid_lines += 1
                continue
            seq = rec.get("seq")
            if not isinstance(seq, int):
                invalid_lines += 1
                continue
            if seq <= start_seq:
                continue
            if end_seq is not None and seq > end_seq:
                continue
            events.append(rec)
            if seq > last_seq:
                last_seq = seq

    return {
        "events": events,
        "invalid_lines": invalid_lines,
        "last_seq": last_seq,
        "path": str(path),
    }


def roll_forward_replay(
    checkpoint_path: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    start_seq: Optional[int] = None,
    end_seq: Optional[int] = None,
) -> Dict[str, Any]:
    resolved_checkpoint_path = _resolve_path(checkpoint_path, CHECKPOINT)
    checkpoint = _read_json_file(resolved_checkpoint_path)
    if checkpoint is None:
        return {
            "ok": False,
            "reason": "checkpoint not found",
            "path": str(resolved_checkpoint_path),
        }

    resolved_snapshot_path = snapshot_path
    if not resolved_snapshot_path:
        snapshot_ref = checkpoint.get("snapshot_path")
        if isinstance(snapshot_ref, str) and snapshot_ref.strip():
            resolved_snapshot_path = snapshot_ref

    resolved_snapshot_file = _resolve_path(resolved_snapshot_path, SNAPSHOT)
    snapshot = _read_json_file(resolved_snapshot_file)
    if snapshot is None:
        return {
            "ok": False,
            "reason": "snapshot not found",
            "path": str(resolved_snapshot_file),
        }

    if start_seq is None:
        checkpoint_seq = checkpoint.get("last_applied_seq")
        if isinstance(checkpoint_seq, int):
            start_seq = checkpoint_seq
        else:
            snapshot_seq = snapshot.get("last_applied_seq")
            if isinstance(snapshot_seq, int):
                start_seq = snapshot_seq
            else:
                start_seq = 0

    journal_result = _read_journal_events(start_seq=start_seq, end_seq=end_seq)
    return {
        "ok": True,
        "checkpoint": checkpoint,
        "checkpoint_path": str(resolved_checkpoint_path),
        "snapshot": snapshot,
        "snapshot_path": str(resolved_snapshot_file),
        "start_seq": start_seq,
        "end_seq": end_seq,
        "events": journal_result["events"],
        "invalid_lines": journal_result["invalid_lines"],
        "last_seq": journal_result["last_seq"],
        "journal_path": journal_result["path"],
    }


def _init_replay_state(snapshot_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    base_state = snapshot_state if isinstance(snapshot_state, dict) else {}
    state: Dict[str, Any] = dict(base_state)
    state.setdefault("session_id", "")
    state.setdefault("current_phase", "")
    state.setdefault("current_task", "")
    state.setdefault("last_action", "")
    state.setdefault("next_step", "")
    state.setdefault("verification_status", "")
    state.setdefault("last_commit", "")
    state.setdefault("last_error", "")

    warnings = state.get("replay_warnings")
    if not isinstance(warnings, dict):
        warnings = {"invalid_lines": 0, "dropped_events": 0}
    warnings.setdefault("invalid_lines", 0)
    warnings.setdefault("dropped_events", 0)
    state["replay_warnings"] = warnings

    applied_event_ids = state.get("applied_event_ids")
    if not isinstance(applied_event_ids, list):
        applied_event_ids = []
    state["applied_event_ids"] = applied_event_ids
    return state


def _select_target_session_id(
    events: List[Dict[str, Any]], preferred: Optional[str]
) -> Optional[str]:
    if preferred:
        return preferred

    latest_session_start_seq = -1
    latest_session_start_id: Optional[str] = None
    latest_any_seq = -1
    latest_any_id: Optional[str] = None

    for event in events:
        seq = event.get("seq")
        session_id = event.get("session_id")
        if not isinstance(seq, int) or not isinstance(session_id, str):
            continue
        if seq > latest_any_seq:
            latest_any_seq = seq
            latest_any_id = session_id
        if event.get("kind") == "session.start" and seq > latest_session_start_seq:
            latest_session_start_seq = seq
            latest_session_start_id = session_id

    return latest_session_start_id or latest_any_id


def _append_applied_event_id(
    state: Dict[str, Any], event_id: str, max_size: int = 10000
) -> None:
    applied_event_ids = state.get("applied_event_ids")
    if not isinstance(applied_event_ids, list):
        applied_event_ids = []
        state["applied_event_ids"] = applied_event_ids
    applied_event_ids.append(event_id)
    if len(applied_event_ids) > max_size:
        applied_event_ids.pop(0)


def _apply_event_to_state(state: Dict[str, Any], event: Dict[str, Any]) -> None:
    kind = event.get("kind")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    if kind == "session.start":
        session_id = event.get("session_id")
        if isinstance(session_id, str):
            state["session_id"] = session_id
        state["current_phase"] = "session"
        state["last_action"] = "session started"
        return

    if kind == "session.end":
        state["last_action"] = "session ended"
        return

    if kind == "task.start":
        title = (
            payload.get("title") if isinstance(payload.get("title"), str) else "unknown"
        )
        state["current_task"] = title
        state["current_phase"] = "task"
        state["last_action"] = "task started"
        return

    if kind == "task.update":
        if not state.get("current_task"):
            state["current_task"] = "unknown"
        status = (
            payload.get("status") if isinstance(payload.get("status"), str) else "task"
        )
        note = (
            payload.get("note")
            if isinstance(payload.get("note"), str)
            else "task updated"
        )
        state["current_phase"] = status
        state["last_action"] = note
        return

    if kind == "task.end":
        if not state.get("current_task"):
            state["current_task"] = "unknown"
        summary = (
            payload.get("summary")
            if isinstance(payload.get("summary"), str)
            else "task ended"
        )
        next_action = (
            payload.get("next_action")
            if isinstance(payload.get("next_action"), str)
            else ""
        )
        state["last_action"] = summary
        state["next_step"] = next_action
        state["current_task"] = ""
        return

    if kind == "verify.start":
        state["verification_status"] = "running"
        state["last_action"] = "verify started"
        return

    if kind == "verify.end":
        ok = payload.get("ok")
        state["verification_status"] = "passed" if ok else "failed"
        state["last_action"] = "verify finished"
        return

    if kind == "commit.start":
        message = payload.get("message")
        if isinstance(message, str) and message:
            state["last_commit"] = message
        state["last_action"] = "commit started"
        return

    if kind == "commit.end":
        sha = payload.get("sha")
        summary = payload.get("summary")
        if isinstance(sha, str) and sha:
            state["last_commit"] = sha
        elif isinstance(summary, str) and summary:
            state["last_commit"] = summary
        state["last_action"] = "commit finished"
        return

    if kind == "file.edit":
        action = payload.get("action")
        path = payload.get("path")
        if isinstance(action, str) and isinstance(path, str):
            state["last_action"] = f"file {action}: {path}"
        return

    if kind == "tool.result":
        ok = payload.get("ok")
        if ok is False:
            error = payload.get("error")
            if isinstance(error, str):
                state["last_error"] = error
        return

    if kind == "error":
        message = payload.get("message")
        if isinstance(message, str):
            state["last_error"] = message
        state["last_action"] = "error recorded"
        return


def replay_events_to_state(
    snapshot_state: Optional[Dict[str, Any]],
    events: List[Dict[str, Any]],
    preferred_session_id: Optional[str] = None,
    invalid_lines: int = 0,
) -> Dict[str, Any]:
    state = _init_replay_state(snapshot_state)
    if invalid_lines:
        state["replay_warnings"]["invalid_lines"] = invalid_lines

    target_session_id = _select_target_session_id(events, preferred_session_id)
    if not target_session_id:
        return state

    for event in events:
        session_id = event.get("session_id")
        if session_id != target_session_id:
            continue
        event_id = event.get("event_id")
        if isinstance(event_id, str) and event_id in state["applied_event_ids"]:
            state["replay_warnings"]["dropped_events"] += 1
            continue
        _apply_event_to_state(state, event)
        if isinstance(event_id, str):
            _append_applied_event_id(state, event_id)

    if not state.get("session_id"):
        state["session_id"] = target_session_id
    return state


def continue_state_rebuild(
    checkpoint_path: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    start_seq: Optional[int] = None,
    end_seq: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    replay = roll_forward_replay(
        checkpoint_path=checkpoint_path,
        snapshot_path=snapshot_path,
        start_seq=start_seq,
        end_seq=end_seq,
    )
    if not replay.get("ok"):
        return replay

    snapshot = replay.get("snapshot") or {}
    snapshot_state = snapshot.get("state") if isinstance(snapshot, dict) else None
    events = replay.get("events") or []
    invalid_lines = (
        replay.get("invalid_lines")
        if isinstance(replay.get("invalid_lines"), int)
        else 0
    )
    state = replay_events_to_state(
        snapshot_state=snapshot_state,
        events=events,
        preferred_session_id=session_id,
        invalid_lines=invalid_lines,
    )

    return {
        "ok": True,
        "state": state,
        "last_applied_seq": replay.get("last_seq"),
        "checkpoint_path": replay.get("checkpoint_path"),
        "snapshot_path": replay.get("snapshot_path"),
        "journal_path": replay.get("journal_path"),
        "start_seq": replay.get("start_seq"),
        "end_seq": replay.get("end_seq"),
        "events_applied": len(events),
    }


def run_verify(timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    if not VERIFY.exists():
        raise FileNotFoundError(f"verify script not found: {VERIFY}")
    _journal_safe("verify.start", {"command": str(VERIFY), "timeout_sec": timeout_sec})
    try:
        result = subprocess.run(
            [str(VERIFY)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        payload = {
            "ok": False,
            "returncode": None,
            "stdout": _truncate_text((exc.stdout or "").strip()),
            "stderr": f"verify timed out after {timeout_sec}s",
        }
        _journal_safe("verify.end", payload)
        return {
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "").strip(),
            "stderr": f"verify timed out after {timeout_sec}s",
        }
    response = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    _journal_safe(
        "verify.end",
        {
            "ok": response["ok"],
            "returncode": response["returncode"],
            "stdout": _truncate_text(response["stdout"]),
            "stderr": _truncate_text(response["stderr"]),
        },
    )
    return response


def git(*args: str) -> str:
    try:
        out = subprocess.check_output(
            ["git", *args], cwd=str(REPO_ROOT), stderr=subprocess.STDOUT
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed or not in PATH") from exc
    except subprocess.CalledProcessError as exc:
        output = exc.output
        if isinstance(output, bytes):
            output_text = output.decode("utf-8", errors="replace").strip()
        else:
            output_text = str(output).strip()
        msg = f"git {' '.join(args)} failed"
        if output_text:
            msg = f"{msg}: {output_text}"
        raise RuntimeError(msg) from exc
    return out.decode("utf-8", errors="replace").strip()


def _git_status_porcelain() -> List[str]:
    out = git("status", "--porcelain")
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _git_diff_stat() -> str:
    return git("diff", "--stat")


def _git_diff_stat_cached() -> str:
    return git("diff", "--stat", "--cached")


def _commit_message_from_status(status_lines: List[str]) -> str:
    count = len(status_lines)
    if count == 0:
        return "chore: no-op"
    return f"chore: update {count} file(s)"


def _auto_snapshot_checkpoint_after_commit() -> Dict[str, Any]:
    if not JOURNAL.exists():
        return {"ok": False, "reason": "journal not found", "path": str(JOURNAL)}

    snapshot = _read_json_file(SNAPSHOT)
    snapshot_state = snapshot.get("state") if isinstance(snapshot, dict) else None
    snapshot_session_id: Optional[str] = None
    snapshot_last_seq: Optional[int] = None

    if isinstance(snapshot, dict):
        snapshot_session_id = snapshot.get("session_id")
        if not isinstance(snapshot_session_id, str):
            snapshot_session_id = None
        snapshot_last_seq = snapshot.get("last_applied_seq")
        if not isinstance(snapshot_last_seq, int):
            snapshot_last_seq = None

    if not snapshot_session_id and isinstance(snapshot_state, dict):
        state_session_id = snapshot_state.get("session_id")
        if isinstance(state_session_id, str):
            snapshot_session_id = state_session_id

    start_seq = snapshot_last_seq or 0
    journal_result = _read_journal_events(start_seq=start_seq)
    events = journal_result.get("events") or []
    invalid_lines = (
        journal_result.get("invalid_lines")
        if isinstance(journal_result.get("invalid_lines"), int)
        else 0
    )
    last_seq = journal_result.get("last_seq")
    if not isinstance(last_seq, int):
        last_seq = start_seq

    if not events and snapshot is None and last_seq == 0:
        return {"ok": False, "reason": "no journal events", "last_seq": last_seq}

    state = replay_events_to_state(
        snapshot_state=snapshot_state,
        events=events,
        preferred_session_id=snapshot_session_id,
        invalid_lines=invalid_lines,
    )
    session_id = snapshot_session_id
    if not session_id and isinstance(state, dict):
        state_session_id = state.get("session_id")
        if isinstance(state_session_id, str):
            session_id = state_session_id

    snapshot_result = snapshot_save(
        state=state, session_id=session_id, last_applied_seq=last_seq
    )
    checkpoint_result = checkpoint_update(
        last_applied_seq=last_seq, snapshot_path=SNAPSHOT.name
    )
    rotation_result = _rotate_journal_if_prev_week()
    if rotation_result.get("rotated"):
        _journal_safe("journal.rotate", rotation_result)
    return {
        "ok": True,
        "snapshot": snapshot_result,
        "checkpoint": checkpoint_result,
        "journal_rotation": rotation_result,
        "last_applied_seq": last_seq,
        "events_applied": len(events),
    }


def commit_if_verified(
    message: str, timeout_sec: Optional[int] = None
) -> Dict[str, str]:
    verify_result = run_verify(timeout_sec=timeout_sec)
    if not verify_result["ok"]:
        raise RuntimeError(
            f"verify failed (code={verify_result['returncode']}): {verify_result['stderr']}"
        )
    _journal_safe("commit.start", {"message": message, "files": "auto"})
    git("add", "-A")

    msg = message.strip().replace("\n", " ")
    if len(msg) > 80:
        msg = msg[:77].rstrip() + "..."

    summary = _git_diff_stat_cached()
    try:
        subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO_ROOT), check=True)
        sha = git("rev-parse", "HEAD")
    except Exception as exc:  # noqa: BLE001
        _journal_safe("commit.end", {"ok": False, "summary": str(exc)})
        raise
    _journal_safe("commit.end", {"ok": True, "sha": sha, "summary": summary})
    try:
        auto_result = _auto_snapshot_checkpoint_after_commit()
        if not auto_result.get("ok"):
            _journal_safe(
                "error",
                {
                    "message": "auto snapshot/checkpoint skipped",
                    "context": auto_result,
                },
            )
    except Exception as exc:  # noqa: BLE001
        _journal_safe(
            "error",
            {"message": "auto snapshot/checkpoint failed", "context": str(exc)},
        )
    return {"sha": sha, "message": msg}


def repo_commit(
    message: Optional[str] = None,
    files: Optional[str] = "auto",
    run_verify: Optional[bool] = None,
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    if run_verify:
        verify_result = run_verify(timeout_sec=timeout_sec)
        if not verify_result["ok"]:
            stderr = (verify_result.get("stderr") or "").strip()
            stdout = (verify_result.get("stdout") or "").strip()
            details = stderr or stdout or "unknown error"
            raise RuntimeError(
                f"verify failed (code={verify_result['returncode']}): {details}"
            )

    _journal_safe("commit.start", {"message": message, "files": files})
    status_lines = _git_status_porcelain()
    if not status_lines:
        _journal_safe("commit.end", {"ok": False, "summary": "no changes to commit"})
        return {"ok": False, "reason": "no changes to commit"}

    resolved_files = files if files is not None else "auto"
    if isinstance(resolved_files, str):
        normalized = resolved_files.strip()
        if not normalized or normalized == "auto":
            resolved_files = "auto"
        else:
            resolved_files = [p.strip() for p in normalized.split(",") if p.strip()]

    if resolved_files == "auto":
        git("add", "-A")
    else:
        if isinstance(resolved_files, list):
            paths = resolved_files
        else:
            paths = [str(resolved_files)]
        if not paths:
            _journal_safe("commit.end", {"ok": False, "summary": "no files specified"})
            return {"ok": False, "reason": "no files specified"}
        git("add", *paths)

    msg = (message or "").strip().replace("\n", " ")
    if not msg:
        msg = _commit_message_from_status(status_lines)
    if len(msg) > 80:
        msg = msg[:77].rstrip() + "..."

    summary = _git_diff_stat_cached()
    try:
        subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO_ROOT), check=True)
        sha = git("rev-parse", "HEAD")
    except Exception as exc:  # noqa: BLE001
        _journal_safe("commit.end", {"ok": False, "summary": str(exc)})
        raise
    _journal_safe("commit.end", {"ok": True, "sha": sha, "summary": summary})
    try:
        auto_result = _auto_snapshot_checkpoint_after_commit()
        if not auto_result.get("ok"):
            _journal_safe(
                "error",
                {
                    "message": "auto snapshot/checkpoint skipped",
                    "context": auto_result,
                },
            )
    except Exception as exc:  # noqa: BLE001
        _journal_safe(
            "error",
            {"message": "auto snapshot/checkpoint failed", "context": str(exc)},
        )
    return {"ok": True, "sha": sha, "message": msg, "summary": summary}


def repo_verify(timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    return run_verify(timeout_sec=timeout_sec)


def repo_status_summary() -> Dict[str, Any]:
    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "status": git("status", "--short"),
        "diff": _git_diff_stat(),
        "staged_diff": _git_diff_stat_cached(),
        "last_commit": git("log", "-1", "--oneline"),
        "files": {
            "unstaged": git("diff", "--name-only"),
            "staged": git("diff", "--name-only", "--cached"),
        },
    }


def repo_commit_message_suggest(diff: Optional[str] = None) -> Dict[str, Any]:
    if diff is None:
        diff_stat = _git_diff_stat_cached() or _git_diff_stat()
        files_blob = "\n".join(
            line
            for line in [
                git("diff", "--name-only", "--cached"),
                git("diff", "--name-only"),
            ]
            if line
        )
        file_list = _parse_changed_files(files_blob)
    else:
        diff_stat = diff
        file_list = _parse_changed_files(diff)

    def _is_code_path(path: str) -> bool:
        return any(path.endswith(ext) for ext in CODE_SUFFIXES)

    has_docs = any(
        path.startswith("docs/") or path.endswith(".md") for path in file_list
    )
    has_tests = any(_is_test_path(path) for path in file_list)
    has_code = any(_is_code_path(path) for path in file_list)
    has_config = any(
        path.endswith((".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".lock"))
        for path in file_list
    )

    if has_docs and not has_code and not has_tests:
        prefix = "docs"
    elif has_tests and not has_code:
        prefix = "test"
    elif has_code:
        prefix = "feat"
    elif has_config:
        prefix = "chore"
    else:
        prefix = "chore"

    suggestions = [
        f"{prefix}: update changes",
        f"{prefix}: adjust files",
        f"{prefix}: refresh repo",
    ]
    return {"suggestions": suggestions, "diff": diff_stat, "files": file_list}


def session_capture_context(
    run_verify: bool = False, log: bool = False
) -> Dict[str, Any]:
    context = {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "status": git("status", "--short"),
        "diff": _git_diff_stat(),
        "staged_diff": _git_diff_stat_cached(),
        "last_commit": git("log", "-1", "--oneline"),
        "files": {
            "unstaged": git("diff", "--name-only"),
            "staged": git("diff", "--name-only", "--cached"),
        },
    }

    if run_verify:
        verify_fn = globals().get("run_verify")
        if callable(verify_fn):
            context["verify"] = verify_fn()
        else:
            context["verify"] = {"ok": False, "error": "verify unavailable"}

    return context


def _unique_preserve_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _is_test_path(path: str) -> bool:
    return (
        "/tests/" in path
        or path.startswith("tests/")
        or "/test/" in path
        or path.startswith("test/")
        or "/__tests__/" in path
        or path.startswith("__tests__/")
    )


def _normalize_test_candidate(path: str, suffix: str) -> str:
    if not suffix:
        return path
    if re.search(r"(?:^|/)(test_.*|.*_test)" + re.escape(suffix) + r"$", path):
        return path
    if _is_test_path(path):
        return re.sub(rf"{re.escape(suffix)}$", rf"_test{suffix}", path)
    return path


def _test_candidates_for_path(path: str) -> List[str]:
    if _is_test_path(path):
        return [path]

    p = Path(path)
    suffixes = p.suffixes
    if not suffixes or not any(s in CODE_SUFFIXES for s in suffixes):
        return []

    suffix = "".join(suffixes)
    stem = p.name[: -len(suffix)] if suffix else p.name
    candidates: List[str] = []

    candidates.append(str(p.with_name(f"{stem}_test{suffix}")))
    candidates.append(str(p.with_name(f"test_{stem}{suffix}")))

    if "/src/" in path:
        candidates.append(path.replace("/src/", "/tests/"))
        candidates.append(path.replace("/src/", "/test/"))
        candidates.append(path.replace("/src/", "/__tests__/"))
    elif path.startswith("src/"):
        candidates.append(path.replace("src/", "tests/", 1))
        candidates.append(path.replace("src/", "test/", 1))
        candidates.append(path.replace("src/", "__tests__/", 1))

    for marker in ("/lib/", "/app/", "/pkg/"):
        if marker in path:
            candidates.append(path.replace(marker, "/tests/"))
            candidates.append(path.replace(marker, "/test/"))

    normalized = [_normalize_test_candidate(c, suffix) for c in candidates]
    return _unique_preserve_order(normalized)


def _parse_changed_files(diff: str) -> List[str]:
    if "diff --git " in diff:
        changed_files: List[str] = []
        for line in diff.splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split()
            if len(parts) >= 4:
                path = parts[2]
                if path.startswith("a/"):
                    path = path[2:]
                changed_files.append(path)
        return changed_files
    return [line.strip() for line in diff.splitlines() if line.strip()]


def tests_suggest(
    diff: Optional[str] = None, failures: Optional[str] = None
) -> Dict[str, Any]:
    if diff is None:
        diff = "\n".join(
            line
            for line in [
                git("diff", "--name-only"),
                git("diff", "--name-only", "--cached"),
            ]
            if line
        )

    suggestions: List[Dict[str, str]] = []
    seen_paths: set[str] = set()

    def _add(path: str, reason: str) -> None:
        if path in seen_paths:
            return
        seen_paths.add(path)
        suggestions.append({"path": path, "reason": reason})

    changed_files = _parse_changed_files(diff)

    for path in changed_files:
        candidates = _test_candidates_for_path(path)
        if not candidates:
            continue
        if _is_test_path(path):
            for candidate in candidates:
                _add(candidate, "existing test changed")
        else:
            for candidate in candidates:
                _add(candidate, f"covers {path}")

    if failures:
        _add("(investigate)", "verify failures present")

    if not suggestions:
        suggestions.append({"path": "(none)", "reason": "no obvious test targets"})

    return {"suggestions": suggestions}


def tests_suggest_from_failures(log_path: str) -> Dict[str, Any]:
    if not log_path:
        raise ValueError("log_path is required")
    path = Path(log_path)
    if not path.is_absolute():
        path = REPO_ROOT / log_path
    if not path.exists():
        raise FileNotFoundError(f"log not found: {path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    return tests_suggest(failures=content)


TOOL_REGISTRY = {
    "commit_if_verified": {
        "description": "Run verify, commit changes, and return commit info",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "timeout_sec": {"type": ["integer", "null"]},
            },
            "required": ["message"],
        },
        "handler": commit_if_verified,
    },
    "journal_append": {
        "description": "Append an event to .agent/journal.jsonl",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "payload": {"type": "object"},
                "session_id": {"type": ["string", "null"]},
                "agent_id": {"type": ["string", "null"]},
                "event_id": {"type": ["string", "null"]},
            },
            "required": ["kind", "payload"],
        },
        "handler": journal_append,
    },
    "snapshot_save": {
        "description": "Save snapshot state to .agent/snapshot.json",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "object"},
                "session_id": {"type": ["string", "null"]},
                "last_applied_seq": {"type": ["integer", "null"]},
                "snapshot_id": {"type": ["string", "null"]},
            },
            "required": ["state"],
        },
        "handler": snapshot_save,
    },
    "snapshot_load": {
        "description": "Load snapshot state from .agent/snapshot.json",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": snapshot_load,
    },
    "checkpoint_update": {
        "description": "Update checkpoint.json with last applied sequence",
        "input_schema": {
            "type": "object",
            "properties": {
                "last_applied_seq": {"type": "integer"},
                "snapshot_path": {"type": ["string", "null"]},
                "checkpoint_id": {"type": ["string", "null"]},
            },
            "required": ["last_applied_seq"],
        },
        "handler": checkpoint_update,
    },
    "checkpoint_read": {
        "description": "Read checkpoint.json",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": checkpoint_read,
    },
    "roll_forward_replay": {
        "description": "Replay journal events from checkpoint/snapshot",
        "input_schema": {
            "type": "object",
            "properties": {
                "checkpoint_path": {"type": ["string", "null"]},
                "snapshot_path": {"type": ["string", "null"]},
                "start_seq": {"type": ["integer", "null"]},
                "end_seq": {"type": ["integer", "null"]},
            },
            "required": [],
        },
        "handler": roll_forward_replay,
    },
    "continue_state_rebuild": {
        "description": "Rebuild continue-ready state from replayed events",
        "input_schema": {
            "type": "object",
            "properties": {
                "checkpoint_path": {"type": ["string", "null"]},
                "snapshot_path": {"type": ["string", "null"]},
                "start_seq": {"type": ["integer", "null"]},
                "end_seq": {"type": ["integer", "null"]},
                "session_id": {"type": ["string", "null"]},
            },
            "required": [],
        },
        "handler": continue_state_rebuild,
    },
    "repo_verify": {
        "description": "Run .zed/scripts/verify and return results",
        "input_schema": {
            "type": "object",
            "properties": {"timeout_sec": {"type": ["integer", "null"]}},
            "required": [],
        },
        "handler": repo_verify,
    },
    "repo_commit": {
        "description": "Commit changes with optional message and file selection",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": ["string", "null"]},
                "files": {"type": ["string", "null"]},
                "run_verify": {"type": ["boolean", "null"]},
                "timeout_sec": {"type": ["integer", "null"]},
            },
            "required": [],
        },
        "handler": repo_commit,
    },
    "repo_status_summary": {
        "description": "Summarize repo status, diff stats, and last commit",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": repo_status_summary,
    },
    "repo_commit_message_suggest": {
        "description": "Suggest commit messages from diff",
        "input_schema": {
            "type": "object",
            "properties": {"diff": {"type": ["string", "null"]}},
            "required": [],
        },
        "handler": repo_commit_message_suggest,
    },
    "session_capture_context": {
        "description": "Capture repo context (branch/status/diff/last commit)",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_verify": {"type": ["boolean", "null"]},
                "log": {"type": ["boolean", "null"]},
            },
            "required": [],
        },
        "handler": session_capture_context,
    },
    "tests_suggest": {
        "description": "Suggest tests based on diff and failures",
        "input_schema": {
            "type": "object",
            "properties": {
                "diff": {"type": ["string", "null"]},
                "failures": {"type": ["string", "null"]},
            },
            "required": [],
        },
        "handler": tests_suggest,
    },
    "tests_suggest_from_failures": {
        "description": "Suggest tests based on a failure log file",
        "input_schema": {
            "type": "object",
            "properties": {"log_path": {"type": "string"}},
            "required": ["log_path"],
        },
        "handler": tests_suggest_from_failures,
    },
}


def tools_list() -> Dict[str, Any]:
    tools = []
    for name, spec in TOOL_REGISTRY.items():
        input_schema = dict(spec["input_schema"])
        properties = dict(input_schema.get("properties") or {})
        properties["workspace_root"] = {"type": ["string", "null"]}
        input_schema["properties"] = properties
        input_schema["required"] = list(input_schema.get("required") or [])
        tools.append(
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": input_schema,
            }
        )
    return {"tools": tools}


def tools_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    resolved_name = name

    alias_map = {
        "journal.append": "journal_append",
        "snapshot.save": "snapshot_save",
        "snapshot.load": "snapshot_load",
        "checkpoint.update": "checkpoint_update",
        "checkpoint.read": "checkpoint_read",
        "roll_forward.replay": "roll_forward_replay",
        "continue.state_rebuild": "continue_state_rebuild",
        "session.capture_context": "session_capture_context",
        "repo.verify": "repo_verify",
        "repo.commit": "repo_commit",
        "repo.status_summary": "repo_status_summary",
        "repo.commit_message_suggest": "repo_commit_message_suggest",
        "tests.suggest": "tests_suggest",
        "tests.suggest_from_failures": "tests_suggest_from_failures",
    }

    if resolved_name not in TOOL_REGISTRY:
        resolved_name = alias_map.get(resolved_name, resolved_name)

    if resolved_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {name}")

    previous_root = REPO_ROOT
    workspace_root = arguments.get("workspace_root") if arguments else None
    if isinstance(workspace_root, str) and workspace_root.strip():
        _set_repo_root(Path(workspace_root).expanduser().resolve())
        arguments = {k: v for k, v in arguments.items() if k != "workspace_root"}

    handler = TOOL_REGISTRY[resolved_name]["handler"]
    call_id = str(uuid.uuid4())
    _journal_safe(
        "tool.call",
        {
            "call_id": call_id,
            "tool": resolved_name,
            "args": _sanitize_args(arguments),
        },
    )
    try:
        result = handler(**arguments) if arguments else handler()  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001
        _journal_safe(
            "tool.result", {"call_id": call_id, "ok": False, "error": str(exc)}
        )
        raise
    finally:
        _set_repo_root(previous_root)
    _journal_safe(
        "tool.result",
        {"call_id": call_id, "ok": True, "result": _summarize_result(result)},
    )
    content_payload = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ]
    }
    return content_payload


def handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    params = req.get("params") or {}
    req_id = req.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "agentops-server", "version": "0.2.0"},
            "capabilities": {"tools": {}},
        }
    elif method == "initialized":
        result = None
    elif method == "shutdown":
        result = None
    elif method == "exit":
        sys.exit(0)
    elif method == "tools/list":
        result = tools_list()
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            raise ValueError("tools/call requires 'name' (string)")
        if not isinstance(arguments, dict):
            raise ValueError("tools/call requires 'arguments' (object)")
        result = tools_call(name, arguments)
    else:
        raise ValueError(f"Unknown method: {method}")

    if req_id is None:
        return None
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("Request must be a JSON object")
            req_id = req.get("id") if isinstance(req, dict) else None
            resp = handle_request(req)
            if resp is not None:
                _write_json(resp)
        except Exception as exc:  # noqa: BLE001
            req_id = None
            try:
                req_id = req.get("id") if isinstance(req, dict) else None
            except Exception:  # noqa: BLE001
                req_id = None
            _journal_safe("error", {"message": str(exc), "kind": "request"})
            if req_id is not None:
                _write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


if __name__ == "__main__":
    main()
