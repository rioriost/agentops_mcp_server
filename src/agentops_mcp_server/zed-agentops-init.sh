#!/usr/bin/env bash
set -euo pipefail

update_mode=0
root=""

usage() {
  echo "Usage: $0 <root> [--update]"
  echo "       $0 --update <root>"
}

for arg in "$@"; do
  case "$arg" in
    --update)
      update_mode=1
      ;;
    *)
      if [ -z "$root" ]; then
        root="${arg%/}"
        if [ -z "$root" ]; then
          root="$arg"
        fi
      else
        echo "Error: unexpected argument: $arg"
        usage
        exit 1
      fi
      ;;
  esac
done

if [ -z "$root" ]; then
  usage
  exit 1
fi

if [ -e "$root" ] && [ ! -d "$root" ]; then
  echo "Error: $root exists and is not a directory."
  exit 1
fi

if (( update_mode == 1 )); then
  if [ ! -d "$root" ]; then
    echo "Error: $root does not exist or is not a directory."
    exit 1
  fi

  managed_hint=0
  if [ -d "$root/.agent" ] || [ -d "$root/.zed" ] || [ -f "$root/.rules" ]; then
    managed_hint=1
  fi

  if (( managed_hint == 0 )); then
    echo "Warning: $root does not look like an AgentOps-managed directory."
  fi

  echo "Update existing directory $root? [y/N]"
  if [ -r /dev/tty ]; then
    read -r reply < /dev/tty
  else
    read -r reply
  fi
  reply_lc=$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')
  case "$reply_lc" in
    y|yes) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
else
  if [ -d "$root" ]; then
    echo "Directory $root already exists. Continue? [y/N]"
    if [ -r /dev/tty ]; then
      read -r reply < /dev/tty
    else
      read -r reply
    fi
    reply_lc=$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')
    case "$reply_lc" in
      y|yes) ;;
      *) echo "Aborted."; exit 1 ;;
    esac
  fi
fi

if (( update_mode == 0 )); then
  mkdir -p "$root"
  if [ ! -e "$root/.git" ]; then
    ( cd "$root" && git init )
  fi
fi

ZED_DIR="$root/.zed"
ZED_SCRIPTS_DIR="$ZED_DIR/scripts"
AGENT_DIR="$root/.agent"
GITIGNORE_FILE="$root/.gitignore"
VERIFY_REL=".zed/scripts/verify"

CANONICAL_EVENT_LOG_REL=".agent/tx_event_log.jsonl"
CANONICAL_STATE_REL=".agent/tx_state.json"
DERIVED_HANDOFF_REL=".agent/handoff.json"
DERIVED_OBSERVABILITY_REL=".agent/observability_summary.json"

GITIGNORE_ENTRIES=(
  ".zed/"
  ".venv/"
  ".agent/"
  ".rules"
  "__pycache__/"
  "*.py[cod]"
  ".pytest_cache/"
  ".DS_Store"
  ".envrc"
)

mkdir -p "$AGENT_DIR"



# --- .gitignore ---
if [ -e "$GITIGNORE_FILE" ] && [ ! -f "$GITIGNORE_FILE" ]; then
  echo "Skipping .gitignore (path exists and is not a file)."
else
  touch "$GITIGNORE_FILE"
  append_gitignore_entry() {
    local entry="$1"
    if ! grep -qxF "$entry" "$GITIGNORE_FILE"; then
      echo "$entry" >> "$GITIGNORE_FILE"
    fi
  }
  for entry in "${GITIGNORE_ENTRIES[@]}"; do
    append_gitignore_entry "$entry"
  done
fi

# --- .rules ---
SOURCE_RULES="${PWD}/.rules"
if [ -f "$SOURCE_RULES" ]; then
  cp "$SOURCE_RULES" "$SOURCE_RULES.bak"
fi
cat <<'RULES' > "$SOURCE_RULES"
# AgentOps (strict rules)
# Goal: Maximize resumability and stable execution under session interruption.

## Start (mandatory)
- Read/restore in this order:
  1) tx_state (materialized transaction state)
  2) tx_event_log (transaction event log replay if needed)
  3) handoff (derived-only, never canonical)
- Resume decisions must use canonical tx_state + tx_event_log only; handoff is derived.
- Treat `.agent/handoff.json` as derived-only.
- If resume state is incomplete:
  - run ops_resume_brief (or equivalent) and emit a short brief
- Identify active ticket (status != done) and resume it.

## Planning flow (mandatory)
- User provides docs/draft.md.
- Generate docs/__version__/plan.md with phases.
- Split phases into tasks and generate:
  - docs/__version__/tickets_list.json (metadata)
  - docs/__version__/pX-tY.json (full ticket with status/inputs/outputs/deps)
- Ticket status enum: planned, in-progress, checking, verified, committed, done, blocked.

## Work loop (mandatory)
- Tickets are the only unit of work.
- For any code change:
  1) Set status -> in-progress (emit tx.begin if new)
  2) Register file intents before mutation
  3) Implement smallest safe change
  4) Update semantic_summary (required) and user_intent only on explicit user resume intent; persist tx_state after mutation
  5) Run "${VERIFY_REL}"
     - If fails: fix and repeat (update semantic summary)
  6) Set status -> checking
     - Compare acceptance_criteria AND plan.md to avoid omissions
  7) Set status -> verified
  8) Commit changes (emit tx.commit.start/done|fail)
  9) Set status -> committed
  10) Set status -> done (emit tx.end.done|blocked)

## Persistence & logging (mandatory)
- Always record events for plan/task/progress/verify/commit.
- Canonical write ordering: event append → tx_state update → cursor persist.
- semantic_summary is required for non-terminal tx; user_intent is only set on explicit user resume intent.
- Keep log outputs short (summaries over full diffs).
- Prefer diff stats over full diffs.

## Handoff & session safety (mandatory)
- When a tool execution adds/modifies files:
  1) ops_compact_context (compact context)
  2) ops_capture_state (snapshot + checkpoint)
  3) ops_handoff_export (handoff summary, optional file write)

## Tooling (mandatory)
- Prefer MCP tools if available.
- Use:
  - journal_append
  - tx_event_append
  - tx_state_save
  - tx_state_rebuild
  - snapshot_save
  - checkpoint_update
  - roll_forward_replay / continue_state_rebuild (if needed)
  - ops_compact_context
  - ops_handoff_export
  - ops_resume_brief
  - repo_commit


## Commit rules (mandatory)
- After verify: check repo status; commit only if changes exist.
- Commit message: ~80 chars, add scope if useful.

## Token discipline (mandatory)
- Keep outputs short; avoid large logs.
- Prefer summaries and diff stats.
RULES

if [ -e "$root/.rules" ] && [ ! -f "$root/.rules" ]; then
  echo "Skipping .rules (path exists and is not a file)."
elif [ -f "$root/.rules" ] && (( update_mode == 0 )); then
  echo "Skipping .rules (already exists)."
else
  if [ -f "$root/.rules" ] && (( update_mode == 1 )); then
    cp "$root/.rules" "$root/.rules.bak"
  fi
  cp "$SOURCE_RULES" "$root/.rules"
fi



# --- canonical tx artifacts ---
if [ -f "$AGENT_DIR/tx_event_log.jsonl" ]; then
  echo "Skipping .agent/tx_event_log.jsonl (already exists)."
else
  touch "$AGENT_DIR/tx_event_log.jsonl"
fi

if [ -f "$AGENT_DIR/tx_state.json" ]; then
  echo "Skipping .agent/tx_state.json (already exists)."
else
  tx_state_ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '%s\n' \
    '{' \
    '  "schema_version": "0.4.0",' \
    "  \"updated_at\": \"$tx_state_ts\"," \
    '  "active_tx": {' \
    '    "tx_id": "",' \
    '    "ticket_id": "",' \
    '    "status": "planned",' \
    '    "phase": "planned",' \
    '    "current_step": "none",' \
    '    "last_completed_step": "",' \
    '    "next_action": "",' \
    '    "semantic_summary": "Initialized transaction state",' \
    '    "user_intent": null,' \
    '    "verify_state": {"status": "not_started", "last_result": null},' \
    '    "commit_state": {"status": "not_started", "last_result": null},' \
    '    "file_intents": []' \
    '  },' \
    '  "last_applied_seq": 0,' \
    '  "integrity": {"state_hash": "", "rebuilt_from_seq": 0}' \
    '}' > "$AGENT_DIR/tx_state.json"
fi



if (( update_mode == 1 )); then
  echo "Skipping .zed scaffold (update mode)."
elif [ -e "$ZED_DIR" ] && [ ! -d "$ZED_DIR" ]; then
  echo "Skipping .zed scaffold (path exists and is not a directory)."
elif [ -e "$ZED_DIR" ]; then
  echo "Skipping .zed scaffold (already exists)."
else
  mkdir -p "$ZED_SCRIPTS_DIR"

  # --- .zed/scripts/verify (polyglot-ish) ---
  {
    printf '%s\n' \
      '#!/usr/bin/env bash' \
      'set -euo pipefail' \
      'cd "$(git rev-parse --show-toplevel)"' \
      '' \
      'echo "==> verify: start"' \
      '' \
      "mapfile -d '' status_entries < <(git status --porcelain -z)" \
      'if (( ${#status_entries[@]} == 0 )); then' \
      '  echo "==> verify: no changes; skipping"' \
      '  exit 0' \
      'fi' \
      '' \
      'has_python=0' \
      'has_swift=0' \
      'has_rust=0' \
      'sh_files=()' \
      'bicep_files=()' \
      '' \
      'for entry in "${status_entries[@]}"; do' \
      '  if [[ "$entry" == *" "* ]]; then' \
      '    path="${entry#?? }"' \
      '  else' \
      '    path="$entry"' \
      '  fi' \
      '  case "$path" in' \
      '    *.py|pyproject.toml|requirements.txt) has_python=1 ;;' \
      '    *.swift|Package.swift) has_swift=1 ;;' \
      '    *.rs|Cargo.toml) has_rust=1 ;;' \
      '    *.sh) sh_files+=("$path") ;;' \
      '    *.bicep) bicep_files+=("$path") ;;' \
      '  esac' \
      'done' \
      '' \
      'ran=0' \
      '' \
      'have_cmd() { command -v "$1" >/dev/null 2>&1; }' \
      'skip_cmd() { echo "==> $1: $2 not installed; skipping"; }' \
      '' \
      'if (( has_python == 1 )); then' \
      '  if have_cmd python; then' \
      '    if python -m pytest --version >/dev/null 2>&1; then' \
      '      echo "==> python: pytest"' \
      '      python -m pytest -q && ran=1 || exit 1' \
      '    else' \
      '      skip_cmd "python" "pytest"' \
      '    fi' \
      '  else' \
      '    skip_cmd "python" "python"' \
      '  fi' \
      'fi' \
      '' \
      'if (( has_swift == 1 )); then' \
      '  if have_cmd swift; then' \
      '    echo "==> swift: swift test"' \
      '    swift test && ran=1 || exit 1' \
      '  else' \
      '    skip_cmd "swift" "swift"' \
      '  fi' \
      'fi' \
      '' \
      'if (( has_rust == 1 )); then' \
      '  if have_cmd cargo; then' \
      '    echo "==> rust: cargo test"' \
      '    cargo test && ran=1 || exit 1' \
      '  else' \
      '    skip_cmd "rust" "cargo"' \
      '  fi' \
      'fi' \
      '' \
      'if (( ${#sh_files[@]} > 0 )); then' \
      '  if have_cmd shellcheck; then' \
      '    echo "==> bash: shellcheck"' \
      '    shellcheck "${sh_files[@]}" && ran=1 || exit 1' \
      '  else' \
      '    skip_cmd "bash" "shellcheck"' \
      '  fi' \
      'fi' \
      '' \
      'if (( ${#bicep_files[@]} > 0 )); then' \
      '  if have_cmd az; then' \
      '    echo "==> bicep: az bicep lint"' \
      '    for bicep_file in "${bicep_files[@]}"; do' \
      '      az bicep lint -f "$bicep_file" && ran=1 || exit 1' \
      '    done' \
      '  elif have_cmd bicep; then' \
      '    echo "==> bicep: bicep lint"' \
      '    for bicep_file in "${bicep_files[@]}"; do' \
      '      bicep lint "$bicep_file" && ran=1 || exit 1' \
      '    done' \
      '  else' \
      '    skip_cmd "az/bicep" "az/bicep"' \
      '  fi' \
      'fi' \
      '' \
      'if [[ "$ran" -eq 0 ]]; then' \
      '  echo "WARN: No known test/build targets detected. Add checks to .zed/scripts/verify."' \
      'fi' \
      '' \
      'echo "==> verify: OK"'
  } > "$ZED_SCRIPTS_DIR/verify"
  chmod +x "$ZED_SCRIPTS_DIR/verify"

  # --- .zed/tasks.json ---
  printf '%s\n' \
    '[' \
    '  {' \
    '    "label": "verify",' \
    "    \"command\": \"./${VERIFY_REL}\"" \
    '  },' \
    '  {' \
    '    "label": "git status",' \
    '    "command": "git status -sb"' \
    '  },' \
    '  {' \
    '    "label": "git diff",' \
    '    "command": "git diff"' \
    '  }' \
    ']' > "$root/.zed/tasks.json"
fi

if (( update_mode == 1 )); then
  echo "Updated AgentOps scaffold in: $root"
else
  echo "Initialized AgentOps scaffold in: $root"
  echo "Next:"
  echo "  - Open $root in Zed"
fi
