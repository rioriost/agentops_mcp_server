# T-011 Input Draft: Replay-to-State Rules

## Purpose
Provide a concrete, implementable mapping from replayed journal events to a reconstructed `state` for the continue flow.

## Scope
- Applies to roll-forward replay after loading `snapshot.json` and `checkpoint.json`.
- Uses `journal.jsonl` events ordered by `seq`.
- Produces a deterministic state suitable for T-011 continue API.

---

## Assumptions
- `seq` is authoritative for ordering.
- Replay ignores invalid JSON lines but records a warning count.
- `event_id` is available for idempotent application.
- `session_id` is present on relevant events; events without `session_id` are ignored by default.

---

## Minimal State Shape (v0.1.0)
Required keys for continue readiness:

- `session_id` (string)
- `current_phase` (string)
- `current_task` (string)
- `last_action` (string)
- `next_step` (string)
- `verification_status` (string)
- `last_commit` (string)
- `last_error` (string)
- `replay_warnings` (object)

Optional:
- `task_history` (list of short strings, bounded)
- `applied_event_ids` (set/list for idempotency)

---

## Replay Rules (Global)

1. **Session filter**
   - If a target `session_id` is provided, ignore events from other sessions.
   - Events without `session_id` are ignored by default.

2. **Idempotency**
   - Track `event_id` in `applied_event_ids`.
   - Skip event if `event_id` already applied.

3. **Ordering**
   - Apply strictly in increasing `seq`.

4. **Invalid lines**
   - Count invalid JSON lines as `replay_warnings.invalid_lines`.

---

## Event → State Mapping

### `session.start`
- `state.session_id = session_id`
- `state.current_phase = "session"`
- `state.last_action = "session started"`

### `session.end`
- `state.last_action = "session ended"`
- Optionally clear `state.next_step`

### `task.start`
- `state.current_task = payload.title or "unknown"`
- `state.current_phase = "task"`
- `state.last_action = "task started"`
- Append to `task_history` if enabled

### `task.update`
- `state.current_phase = payload.status or "task"`
- `state.last_action = payload.note or "task updated"`
- If `current_task` empty, set `"unknown"`

### `task.end`
- `state.last_action = payload.summary or "task ended"`
- `state.next_step = payload.next_action or ""`
- `state.current_task = ""`

### `verify.start`
- `state.verification_status = "running"`
- `state.last_action = "verify started"`

### `verify.end`
- `state.verification_status = "passed" if ok else "failed"`
- `state.last_action = "verify finished"`

### `commit.start`
- `state.last_action = "commit started"`
- `state.last_commit = payload.message or state.last_commit`

### `commit.end`
- `state.last_action = "commit finished"`
- `state.last_commit = payload.sha or payload.summary or state.last_commit`

### `file.edit`
- `state.last_action = f"file {payload.action}: {payload.path}"`

### `tool.call` / `tool.result`
- Default: **no state mutation**
- Optional: if `tool.result.ok` is false, set `state.last_error`

### `error`
- `state.last_error = payload.message`
- `state.last_action = "error recorded"`

---

## Missing/Out-of-Order Event Handling

- `task.end` without prior `task.start`:
  - Set `current_task = "unknown"` then apply end logic.
- `task.update` without prior `task.start`:
  - Set `current_task = "unknown"` and apply update.

---

## Output Contract for Replay

Return:
- `state` (updated, reconstructed)
- `last_applied_seq`
- `replay_warnings` (invalid_lines, dropped_events, etc.)

---

## Implementation Details (Draft)

### Function Signatures (proposed)
```/dev/null/replay_apply_event.py#L1-80
def init_replay_state(snapshot_state: dict | None) -> dict:
    ...

def select_target_session_id(events: list[dict], preferred: str | None) -> str | None:
    ...

def apply_event_to_state(state: dict, event: dict) -> None:
    ...

def replay_events_to_state(
    snapshot_state: dict | None,
    events: list[dict],
    preferred_session_id: str | None = None,
) -> dict:
    ...
```

### State Initialization
- `init_replay_state` starts from `snapshot.state` if present; otherwise creates a blank state with required keys.
- Default values:
  - `current_phase = ""`
  - `current_task = ""`
  - `last_action = ""`
  - `next_step = ""`
  - `verification_status = ""`
  - `last_commit = ""`
  - `last_error = ""`
  - `replay_warnings = {"invalid_lines": 0, "dropped_events": 0}`

### Session Selection Strategy
- `preferred_session_id` takes precedence if provided.
- Otherwise:
  1. Choose the **latest** `session.start` event by `seq`.
  2. If none, choose the most recent event with `session_id`.
  3. If still none, return `None` (replay no-op).

### Idempotency Strategy
- Use `state.applied_event_ids` as a bounded set (e.g., cap at 10k, evict oldest).
- If `event_id` already applied: skip and increment `replay_warnings.dropped_events`.

### Apply Logic (Pseudocode)
```/dev/null/replay_apply_event.py#L81-180
def replay_events_to_state(snapshot_state, events, preferred_session_id=None):
    state = init_replay_state(snapshot_state)
    target_session_id = select_target_session_id(events, preferred_session_id)
    for event in events:
        session_id = event.get("session_id")
        if target_session_id and session_id != target_session_id:
            continue
        if not session_id:
            continue
        event_id = event.get("event_id")
        if event_id and event_id in state["applied_event_ids"]:
            state["replay_warnings"]["dropped_events"] += 1
            continue
        apply_event_to_state(state, event)
        if event_id:
            state["applied_event_ids"].append(event_id)
    return state
```

### Per-Event Apply Details
- `apply_event_to_state` implements the mapping defined in **Event → State Mapping**.
- When `task.end` or `task.update` arrives without `task.start`, set `current_task = "unknown"` before applying.
- `tool.call` / `tool.result`: ignore by default; set `last_error` only when `ok == False`.

### Output Contract
- Return `state` and `last_applied_seq`.
- `replay_warnings` includes `invalid_lines` and `dropped_events`.

---

## Open Decisions (T-011)
- How to select target `session_id` if not provided.
- Whether to allow events without `session_id` in reconstruction.
- Whether to persist `applied_event_ids` in snapshot to avoid growth.