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
- handoff_read() -> returns structured handoff content
- handoff_update(summary, decisions, next_actions, risks?, links?) -> updates handoff
- handoff_normalize() -> normalize handoff section order
- session_log_append(kind|event|text, data?) -> append to session log
- session_capture_context(run_verify?, log?) -> capture repo context
- session_checkpoint(actor, label?) -> create a diff checkpoint
- session_diff_since_checkpoint(checkpoint_id) -> compute diff since a checkpoint
- repo_verify(timeout_sec?) -> run verify script
- repo_commit(message?, files="auto") -> commit changes
- repo_status_summary() -> summarize repo status and diff
- repo_commit_message_suggest(diff?) -> suggest commit messages
- tests_suggest(diff?, failures?) -> suggest tests
- tests_suggest_from_failures(log_path) -> suggest tests from failure logs
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _resolve_repo_root() -> Path:
    env_root = os.getenv("AGENTOPS_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=str(Path.cwd())
        )
        return Path(out.decode("utf-8").strip()).resolve()
    except Exception:
        return Path.cwd().resolve()


REPO_ROOT = _resolve_repo_root()
HANDOFF = REPO_ROOT / ".agent" / "handoff.md"
SESSION_LOG = REPO_ROOT / ".agent" / "session-log.jsonl"
CHECKPOINTS_DIR = REPO_ROOT / ".agent" / "checkpoints"
VERIFY = REPO_ROOT / ".zed" / "scripts" / "verify"

SECTION_ORDER: List[Tuple[str, str]] = [
    ("Current goal", "summary"),
    ("Decisions", "decisions"),
    ("Changes since last session", "changes"),
    ("Verification status", "verification"),
    ("Risks", "risks"),
    ("Links", "links"),
    ("Next actions", "next_actions"),
]
LEGACY_EVENT_HEADER = "Last event"
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

LOG_TIMING = os.getenv("AGENTOPS_LOG_TIMING", "").lower() in {"1", "true", "yes", "on"}
LOG_PATH = os.getenv("AGENTOPS_LOG_PATH", "").strip() or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_timing(event: str, **data: Any) -> None:
    if not LOG_TIMING:
        return
    payload = {"ts": _now_iso(), "event": event, **data}
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    if LOG_PATH:
        _ensure_parent(Path(LOG_PATH))
        with Path(LOG_PATH).open("a", encoding="utf-8") as f:
            f.write(line)
        return
    sys.stderr.write(line)
    sys.stderr.flush()


def _write_json(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_text(path: Path) -> Optional[str]:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_text(path: Path, content: str) -> None:
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8")


def _strip_trailing_blank_lines(text: str) -> str:
    return re.sub(r"\s+\Z", "\n", text, flags=re.DOTALL)


def _normalize_section_content(text: str) -> str:
    return text.strip("\n").rstrip() + "\n"


def _parse_handoff_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    if not text:
        return sections

    lines = text.splitlines()
    current_title: Optional[str] = None
    buffer: List[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                sections[current_title] = "\n".join(buffer).strip("\n")
            current_title = line[3:].strip()
            buffer = []
        else:
            buffer.append(line)

    if current_title is not None:
        sections[current_title] = "\n".join(buffer).strip("\n")

    return sections


def _render_handoff(sections: Dict[str, str]) -> str:
    content = ["# Handoff", ""]
    for title, key in SECTION_ORDER:
        section_text = sections.get(title)
        if section_text is None:
            continue
        content.append(f"## {title}")
        content.append(section_text.rstrip())
        content.append("")

    # Preserve legacy "Last event" section if present.
    if LEGACY_EVENT_HEADER in sections:
        content.append(f"## {LEGACY_EVENT_HEADER}")
        content.append(sections[LEGACY_EVENT_HEADER].rstrip())
        content.append("")

    return _strip_trailing_blank_lines("\n".join(content))


def _default_handoff_template() -> str:
    defaults = {
        "Current goal": "- (fill)",
        "Decisions": "- (fill)",
        "Changes since last session": "- (fill)",
        "Verification status": "- Last verify: (never)",
        "Next actions": "1. (fill)",
    }
    return _render_handoff(defaults)


def log_append(kind: str, payload: Dict[str, Any]) -> None:
    _ensure_parent(SESSION_LOG)
    rec = {"ts": _now_iso(), "kind": kind, "payload": payload}
    with SESSION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def session_log_append(
    kind: Optional[str] = None,
    event: Optional[str] = None,
    text: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_kind = kind or event or "event"
    payload: Dict[str, Any] = {}
    if event:
        payload["event"] = event
    if text:
        payload["text"] = text
    if data:
        payload["data"] = data
    if not payload:
        payload = {"note": "empty"}
    log_append(resolved_kind, payload)
    return {"ok": True, "kind": resolved_kind}


def run_verify(timeout_sec: Optional[int] = None) -> Dict[str, Any]:
    if not VERIFY.exists():
        raise FileNotFoundError(f"verify script not found: {VERIFY}")
    try:
        result = subprocess.run(
            [str(VERIFY)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": (exc.stdout or "").strip(),
            "stderr": f"verify timed out after {timeout_sec}s",
        }
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


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


def commit_if_verified(
    message: str, timeout_sec: Optional[int] = None
) -> Dict[str, str]:
    verify_result = run_verify(timeout_sec=timeout_sec)
    if not verify_result["ok"]:
        raise RuntimeError(
            f"verify failed (code={verify_result['returncode']}): {verify_result['stderr']}"
        )
    git("add", "-A")

    msg = message.strip().replace("\n", " ")
    if len(msg) > 80:
        msg = msg[:77].rstrip() + "..."

    subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO_ROOT), check=True)
    sha = git("rev-parse", "HEAD")
    log_append("commit", {"sha": sha, "message": msg})
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

    status_lines = _git_status_porcelain()
    if not status_lines:
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
            return {"ok": False, "reason": "no files specified"}
        git("add", *paths)

    msg = (message or "").strip().replace("\n", " ")
    if not msg:
        msg = _commit_message_from_status(status_lines)
    if len(msg) > 80:
        msg = msg[:77].rstrip() + "..."

    summary = _git_diff_stat_cached()
    subprocess.run(["git", "commit", "-m", msg], cwd=str(REPO_ROOT), check=True)
    sha = git("rev-parse", "HEAD")
    log_append("commit", {"sha": sha, "message": msg, "summary": summary})
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

    if log:
        log_append("session_capture", {"context": context})

    return context


def _checkpoint_id(actor: str, label: Optional[str]) -> str:
    if actor not in {"ai", "user"}:
        raise ValueError("actor must be 'ai' or 'user'")
    safe_label = ""
    if label:
        safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label.strip()).strip("-")
    timestamp = _now_iso().replace(":", "-").replace(".", "-")
    if safe_label:
        return f"{actor}-{timestamp}-{safe_label}"
    return f"{actor}-{timestamp}"


def _checkpoint_path(checkpoint_id: str) -> Path:
    return CHECKPOINTS_DIR / f"{checkpoint_id}.json"


def session_checkpoint(actor: str, label: Optional[str] = None) -> Dict[str, Any]:
    checkpoint_id = _checkpoint_id(actor, label)
    snapshot = {
        "id": checkpoint_id,
        "ts": _now_iso(),
        "actor": actor,
        "label": label,
        "status": git("status", "--short"),
        "unstaged_diff": git("diff"),
        "staged_diff": git("diff", "--cached"),
        "full_diff": git("diff", "HEAD"),
    }
    _ensure_parent(_checkpoint_path(checkpoint_id))
    _checkpoint_path(checkpoint_id).write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    log_append(
        "checkpoint",
        {
            "id": checkpoint_id,
            "actor": actor,
            "label": label,
            "unstaged_diff": snapshot["unstaged_diff"],
            "staged_diff": snapshot["staged_diff"],
            "full_diff": snapshot["full_diff"],
        },
    )
    return snapshot


def session_diff_since_checkpoint(checkpoint_id: str) -> Dict[str, Any]:
    path = _checkpoint_path(checkpoint_id)
    if not path.exists():
        raise FileNotFoundError(f"checkpoint not found: {checkpoint_id}")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    current_diff = git("diff", "HEAD")
    checkpoint_diff = snapshot.get("full_diff", "")
    delta_lines = difflib.unified_diff(
        checkpoint_diff.splitlines(),
        current_diff.splitlines(),
        fromfile="checkpoint",
        tofile="current",
        lineterm="",
    )
    delta_diff = "\n".join(delta_lines)
    log_append("checkpoint_diff", {"id": checkpoint_id})
    return {
        "checkpoint": snapshot,
        "current_diff": current_diff,
        "delta_diff": delta_diff,
    }


def _event_section(event: Optional[str], data: Optional[Dict[str, Any]]) -> str:
    event_line = event if event else "(none)"
    data_block = "(none)"
    if data:
        data_block = json.dumps(data, ensure_ascii=False, indent=2)

    return f"## {LEGACY_EVENT_HEADER}\n- Event: {event_line}\n## Event data\n{data_block}\n"


def _upsert_event_section(
    existing_content: str, event: Optional[str], data: Optional[Dict[str, Any]]
) -> str:
    event_section = _event_section(event, data).rstrip() + "\n"
    if f"## {LEGACY_EVENT_HEADER}" not in existing_content:
        return existing_content.rstrip() + "\n\n" + event_section + "\n"

    lines = existing_content.splitlines()
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None

    for i, line in enumerate(lines):
        if line.strip() == f"## {LEGACY_EVENT_HEADER}":
            start_idx = i
            continue
        if start_idx is not None and line.startswith("## ") and i > start_idx:
            end_idx = i
            break

    if start_idx is None:
        return existing_content.rstrip() + "\n\n" + event_section + "\n"

    if end_idx is None:
        end_idx = len(lines)

    new_lines = lines[:start_idx] + event_section.splitlines() + lines[end_idx:]
    return "\n".join(new_lines).rstrip() + "\n"


def _deterministic_handoff(
    event: Optional[str],
    data: Optional[Dict[str, Any]],
    content: Optional[str],
    existing_content: Optional[str],
) -> str:
    if content is not None and content.strip():
        return content.rstrip() + "\n"

    if existing_content is not None and existing_content.strip():
        return _upsert_event_section(existing_content, event, data)

    return (
        "# Handoff\n\n"
        "## Current goal\n"
        "- (fill)\n\n"
        "## Decisions\n"
        "- (fill)\n\n"
        "## Changes since last session\n"
        "- (fill)\n\n"
        "## Verification status\n"
        "- Last verify: (never)\n\n"
        + _event_section(event, data)
        + "\n## Next actions\n"
        "1. (fill)\n"
    )


def handoff_update(
    event: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    content: Optional[str] = None,
) -> None:
    existing_content = _read_text(HANDOFF)
    _write_text(
        HANDOFF,
        _deterministic_handoff(
            event=event,
            data=data,
            content=content,
            existing_content=existing_content,
        ),
    )
    log_append("handoff_update", {"path": str(HANDOFF), "event": event})


def handoff_read() -> Dict[str, Any]:
    content = _read_text(HANDOFF) or ""
    sections = _parse_handoff_sections(content)
    structured = {}
    for title, key in SECTION_ORDER:
        if title in sections:
            structured[key] = sections[title].strip()
    if LEGACY_EVENT_HEADER in sections:
        structured["last_event"] = sections[LEGACY_EVENT_HEADER].strip()
    return {"path": str(HANDOFF), "raw": content, "sections": structured}


def handoff_update_structured(
    summary: Optional[str] = None,
    decisions: Optional[str] = None,
    next_actions: Optional[str] = None,
    risks: Optional[str] = None,
    links: Optional[str] = None,
    changes: Optional[str] = None,
    verification: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _read_text(HANDOFF)
    if not existing:
        base_sections = _parse_handoff_sections(_default_handoff_template())
    else:
        base_sections = _parse_handoff_sections(existing)

    updates: Dict[str, Optional[str]] = {
        "Current goal": summary,
        "Decisions": decisions,
        "Next actions": next_actions,
        "Risks": risks,
        "Links": links,
        "Changes since last session": changes,
        "Verification status": verification,
    }

    if summary is None or decisions is None or next_actions is None:
        raise ValueError("handoff_update requires summary, decisions, and next_actions")

    for title, value in updates.items():
        if value is not None:
            if not value.strip():
                raise ValueError(f"{title} cannot be empty")
            base_sections[title] = _normalize_section_content(value).strip("\n")

    rendered = _render_handoff(base_sections)
    _write_text(HANDOFF, rendered)
    log_append("handoff_update", {"path": str(HANDOFF), "mode": "structured"})
    return {"ok": True, "path": str(HANDOFF)}


def handoff_normalize() -> Dict[str, Any]:
    existing = _read_text(HANDOFF)
    if not existing or not existing.strip():
        template = _default_handoff_template()
        _write_text(HANDOFF, template)
        log_append(
            "handoff_update",
            {"path": str(HANDOFF), "mode": "normalize", "created": True},
        )
        return {"ok": True, "path": str(HANDOFF), "normalized": False}

    sections = _parse_handoff_sections(existing)
    rendered = _render_handoff(sections) if sections else _default_handoff_template()
    _write_text(HANDOFF, rendered)
    log_append("handoff_update", {"path": str(HANDOFF), "mode": "normalize"})
    return {"ok": True, "path": str(HANDOFF), "normalized": True}


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
    "handoff_read": {
        "description": "Read .agent/handoff.md and return structured sections",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": handoff_read,
    },
    "handoff_update": {
        "description": "Update .agent/handoff.md with structured sections",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "decisions": {"type": "string"},
                "next_actions": {"type": "string"},
                "risks": {"type": ["string", "null"]},
                "links": {"type": ["string", "null"]},
                "changes": {"type": ["string", "null"]},
                "verification": {"type": ["string", "null"]},
            },
            "required": ["summary", "decisions", "next_actions"],
        },
        "handler": handoff_update_structured,
    },
    "handoff_normalize": {
        "description": "Normalize .agent/handoff.md section order",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "handler": handoff_normalize,
    },
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
    "log_append": {
        "description": "Append an event to .agent/session-log.jsonl",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["kind", "payload"],
        },
        "handler": log_append,
    },
    "session_log_append": {
        "description": "Append a session event to .agent/session-log.jsonl",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": ["string", "null"]},
                "event": {"type": ["string", "null"]},
                "text": {"type": ["string", "null"]},
                "data": {"type": ["object", "null"]},
            },
            "required": [],
        },
        "handler": session_log_append,
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
    "session_checkpoint": {
        "description": "Create a diff checkpoint for ai/user edits",
        "input_schema": {
            "type": "object",
            "properties": {
                "actor": {"type": "string"},
                "label": {"type": ["string", "null"]},
            },
            "required": ["actor"],
        },
        "handler": session_checkpoint,
    },
    "session_diff_since_checkpoint": {
        "description": "Compute diff since a checkpoint",
        "input_schema": {
            "type": "object",
            "properties": {"checkpoint_id": {"type": "string"}},
            "required": ["checkpoint_id"],
        },
        "handler": session_diff_since_checkpoint,
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
        tools.append(
            {
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["input_schema"],
            }
        )
    return {"tools": tools}


def tools_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    resolved_name = name

    alias_map = {
        "handoff.read": "handoff_read",
        "handoff.update": "handoff_update",
        "handoff.normalize": "handoff_normalize",
        "session.log_append": "session_log_append",
        "session.capture_context": "session_capture_context",
        "session.checkpoint": "session_checkpoint",
        "session.diff_since_checkpoint": "session_diff_since_checkpoint",
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

    handler = TOOL_REGISTRY[resolved_name]["handler"]
    t0 = time.perf_counter()
    _log_timing("tool.start", name=resolved_name)
    result = handler(**arguments) if arguments else handler()  # type: ignore[misc]
    _log_timing(
        "tool.end",
        name=resolved_name,
        elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
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
            method = req.get("method") if isinstance(req, dict) else None
            t0 = time.perf_counter()
            _log_timing("request.start", method=method, request_id=req_id)
            resp = handle_request(req)
            _log_timing(
                "request.end",
                method=method,
                request_id=req_id,
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
            )
            if resp is not None:
                _write_json(resp)
        except Exception as exc:  # noqa: BLE001
            req_id = None
            try:
                req_id = req.get("id") if isinstance(req, dict) else None
            except Exception:  # noqa: BLE001
                req_id = None
            _log_timing("request.error", request_id=req_id, error=str(exc))
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
