#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -h "$SCRIPT_PATH" ]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
  case "$SCRIPT_PATH" in
    /*) ;;
    *) SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_PATH" ;;
  esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"

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
SOURCE_RULES="$root/.agentops-workflow-rules.tmp"
SOURCE_RULES_TEMPLATE="$SCRIPT_DIR/rules_template.txt"
if [ -f "$SOURCE_RULES" ]; then
  cp "$SOURCE_RULES" "$SOURCE_RULES.bak"
fi
if [ -f "$SOURCE_RULES_TEMPLATE" ]; then
  cp "$SOURCE_RULES_TEMPLATE" "$SOURCE_RULES"
else
  echo "Error: no workflow rules source available."
  exit 1
fi

if [ -e "$root/.rules" ] && [ ! -f "$root/.rules" ]; then
  echo "Skipping .rules (path exists and is not a file)."
else
  if [ -f "$root/.rules" ]; then
    cp "$root/.rules" "$root/.rules.bak"
  fi
  cp "$SOURCE_RULES" "$root/.rules"
fi
rm -f "$SOURCE_RULES" "$SOURCE_RULES.bak"



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
    '  "active_tx": {' \
    '    "tx_id": "none",' \
    '    "ticket_id": "none",' \
    '    "status": "planned",' \
    '    "phase": "planned",' \
    '    "current_step": "none",' \
    '    "last_completed_step": "",' \
    '    "next_action": "tx.begin",' \
    '    "semantic_summary": "No active transaction.",' \
    '    "user_intent": null,' \
    '    "session_id": "",' \
    '    "verify_state": {"status": "not_started", "last_result": null},' \
    '    "commit_state": {"status": "not_started", "last_result": null},' \
    '    "file_intents": []' \
    '  },' \
    '  "last_applied_seq": 0,' \
    '  "integrity": {' \
    '    "state_hash": "",' \
    '    "rebuilt_from_seq": 0,' \
    '    "drift_detected": false,' \
    '    "active_tx_source": "none"' \
    '  },' \
    "  \"updated_at\": \"$tx_state_ts\"" \
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
