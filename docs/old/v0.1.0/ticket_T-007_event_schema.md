# T-007 Event kinds and payload schema

## Goal
Define the event kinds and payload schema to be written into `journal.jsonl`.

---

## Journal record (common fields)

Every journal line is a JSON object with these common fields:

- `seq` (int, required): monotonic sequence number.
- `event_id` (uuid string, required): unique event identifier.
- `ts` (RFC3339 string, required): event timestamp.
- `project_root` (string, required): absolute project root path.
- `session_id` (string, optional): session identifier.
- `agent_id` (string, optional): agent identifier.
- `kind` (string, required): one of the event kinds listed below.
- `payload` (object, required): event-specific data.

> Notes:
> - `seq` is the authoritative ordering key.
> - `payload` must be JSON-serializable and stable.

---

## Event kinds and payloads

### 1) `session.start`
**Purpose:** track the beginning of a session.

**Payload:**
- `resume` (bool, required): `true` if resuming from checkpoint.
- `session_label` (string, optional): human-readable label.
- `client` (string, optional): client name/version.

---

### 2) `session.end`
**Purpose:** track the end of a session.

**Payload:**
- `reason` (string, optional): e.g., `user_exit`, `timeout`, `error`.
- `ok` (bool, optional): overall success.
- `summary` (string, optional): brief closure note.

---

### 3) `task.start`
**Purpose:** record task kickoff.

**Payload:**
- `task_id` (string, optional): external task reference (e.g., ticket id).
- `title` (string, required): task title.
- `user_intent` (string, optional): user request summary.

---

### 4) `task.update`
**Purpose:** record task progress.

**Payload:**
- `task_id` (string, optional)
- `status` (string, required): e.g., `in_progress`, `blocked`, `waiting`.
- `note` (string, optional): progress detail.

---

### 5) `task.end`
**Purpose:** record task completion.

**Payload:**
- `task_id` (string, optional)
- `outcome` (string, required): `success`, `failed`, `aborted`.
- `summary` (string, optional): final summary.
- `next_action` (string, optional): suggested follow-up.

---

### 6) `tool.call`
**Purpose:** record tool invocation.

**Payload:**
- `call_id` (uuid string, required): correlation id for call/result pairing.
- `tool` (string, required): tool name.
- `args` (object, optional): arguments (redact sensitive values if needed).

---

### 7) `tool.result`
**Purpose:** record tool result.

**Payload:**
- `call_id` (uuid string, required): matches `tool.call`.
- `ok` (bool, required): success or failure.
- `result` (object, optional): return data (truncate or summarize if large).
- `error` (string, optional): error message on failure.

---

### 8) `file.edit`
**Purpose:** record file edits.

**Payload:**
- `path` (string, required): file path (relative to project root when possible).
- `action` (string, required): `create`, `edit`, `overwrite`, `delete`, `rename`.
- `summary` (string, optional): short description.
- `lines_changed` (int, optional): approximate line count.

---

### 9) `verify.start`
**Purpose:** record verification start.

**Payload:**
- `command` (string, optional): verify command path.
- `timeout_sec` (int, optional)

---

### 10) `verify.end`
**Purpose:** record verification completion.

**Payload:**
- `ok` (bool, required)
- `returncode` (int, optional)
- `stdout` (string, optional; may be truncated)
- `stderr` (string, optional; may be truncated)

---

### 11) `commit.start`
**Purpose:** record commit start.

**Payload:**
- `message` (string, optional): proposed commit message.
- `files` (string | array, optional): commit target files.

---

### 12) `commit.end`
**Purpose:** record commit completion.

**Payload:**
- `ok` (bool, required)
- `sha` (string, optional)
- `summary` (string, optional): diff summary or commit summary.

---

### 13) `error`
**Purpose:** record errors outside specific tool calls.

**Payload:**
- `message` (string, required)
- `kind` (string, optional): error category.
- `context` (object, optional): additional metadata.

---

## Conventions

- Use `call_id` to correlate `tool.call` and `tool.result`.
- Truncate large `stdout`/`stderr` payloads to avoid oversized log entries.
- Redact secrets in `tool.call.args` and `tool.result.result` as needed.
- Keep payload fields stable to simplify replay logic in Phase 3.

---

## Acceptance criteria

- Event kinds and payload fields are documented (this file).
- `kind` values align with the v0.1.0 plan’s minimal event set.
- Common fields are explicit and consistent across all events.