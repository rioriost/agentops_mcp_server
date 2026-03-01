#!/usr/bin/env bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <root>"
  exit 1
fi
root="${1%/}"
if [ -z "$root" ]; then
  root="$1"
fi

if [ -e "$root" ] && [ ! -d "$root" ]; then
  echo "Error: $root exists and is not a directory."
  exit 1
fi

if [ -d "$root" ]; then
  echo "Directory $root already exists. Continue? [y/N]"
  read -r reply
  reply_lc=$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')
  case "$reply_lc" in
    y|yes) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

mkdir -p "$root"
if [ ! -e "$root/.git" ]; then
  ( cd "$root" && git init )
fi

ZED_DIR="$root/.zed"
ZED_SCRIPTS_DIR="$ZED_DIR/scripts"
AGENT_DIR="$root/.agent"
GITIGNORE_FILE="$root/.gitignore"
VERIFY_REL=".zed/scripts/verify"

JOURNAL_REL=".agent/journal.jsonl"
SNAPSHOT_REL=".agent/snapshot.json"
CHECKPOINT_REL=".agent/checkpoint.json"
GITIGNORE_ENTRIES=(
  ".zed/"
  ".venv/"
  ".agent/"
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
if [ -f "$root/.rules" ]; then
  echo "Skipping .rules (already exists)."
else
  cat > "$root/.rules" <<'RULES'
# AgentOps (project rules)
# Goal: Max automation for (1) journal/snapshot/checkpoint persistence, (2) verify->commit loop, (3) test generation.

## Always do this at the start
- Review `.agent/snapshot.json` and `.agent/checkpoint.json` for current state and last applied seq.
- Inspect `.agent/journal.jsonl` for recent events if needed.

## Work loop (mandatory)
- For any code change:
  1) Implement smallest safe change
  2) Run "${VERIFY_REL}"
  3) If it fails: fix and repeat
  4) If it passes: commit changes
  5) Update snapshot/checkpoint as needed

## State persistence (v0.1.0)
- Use `.agent/journal.jsonl` for append-only events.
- Use `.agent/snapshot.json` for state snapshots.
- Use `.agent/checkpoint.json` for roll-forward start.

## Roll-forward recovery
- Rebuild state by replaying journal from checkpoint/snapshot when resuming.
- Use continue-ready state reconstruction if provided.

## Commit message
- ~80 chars, semantic summary (not strict conventional commits)
- Mention scope if useful (e.g. "rust:", "py:", "swift:", "infra:")

## Prefer MCP tools if available
- If MCP tools exist:
  - use mcp:agentops:journal_append for events
  - use mcp:agentops:snapshot_save to persist state
  - use mcp:agentops:checkpoint_update to advance replay
  - use mcp:agentops:roll_forward_replay for recovery
  - use mcp:agentops:continue_state_rebuild for continue-ready state
  - use mcp:agentops:repo_commit to commit after verify

## MCP workspace_root requirement
- When calling MCP tools, always pass `workspace_root` as the absolute project root path.
- If `workspace_root` is omitted, the server falls back to its current working directory.
RULES
fi



# --- journal/snapshot/checkpoint ---
if [ -f "$AGENT_DIR/journal.jsonl" ]; then
  echo "Skipping .agent/journal.jsonl (already exists)."
else
  touch "$AGENT_DIR/journal.jsonl"
fi

if [ -f "$AGENT_DIR/snapshot.json" ]; then
  echo "Skipping .agent/snapshot.json (already exists)."
else
  cat > "$AGENT_DIR/snapshot.json" <<JSON
{
  "snapshot_id": "init",
  "ts": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "project_root": "$root",
  "last_applied_seq": 0,
  "state": {}
}
JSON
fi

if [ -f "$AGENT_DIR/checkpoint.json" ]; then
  echo "Skipping .agent/checkpoint.json (already exists)."
else
  cat > "$AGENT_DIR/checkpoint.json" <<JSON
{
  "checkpoint_id": "init",
  "ts": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "project_root": "$root",
  "last_applied_seq": 0,
  "snapshot_path": "snapshot.json"
}
JSON
fi

if [ -e "$ZED_DIR" ] && [ ! -d "$ZED_DIR" ]; then
  echo "Skipping .zed scaffold (path exists and is not a directory)."
elif [ -e "$ZED_DIR" ]; then
  echo "Skipping .zed scaffold (already exists)."
else
  mkdir -p "$ZED_SCRIPTS_DIR"

  # --- .zed/scripts/verify (polyglot-ish) ---
  cat > "$ZED_SCRIPTS_DIR/verify" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "==> verify: start"

mapfile -d '' status_entries < <(git status --porcelain -z)
if (( ${#status_entries[@]} == 0 )); then
  echo "==> verify: no changes; skipping"
  exit 0
fi

has_python=0
has_swift=0
has_rust=0
sh_files=()
bicep_files=()

for entry in "${status_entries[@]}"; do
  if [[ "$entry" == *" "* ]]; then
    path="${entry#?? }"
  else
    path="$entry"
  fi
  case "$path" in
    *.py|pyproject.toml|requirements.txt) has_python=1 ;;
    *.swift|Package.swift) has_swift=1 ;;
    *.rs|Cargo.toml) has_rust=1 ;;
    *.sh) sh_files+=("$path") ;;
    *.bicep) bicep_files+=("$path") ;;
  esac
done

ran=0

have_cmd() { command -v "$1" >/dev/null 2>&1; }
skip_cmd() { echo "==> $1: $2 not installed; skipping"; }

if (( has_python == 1 )); then
  if have_cmd python; then
    if python -m pytest --version >/dev/null 2>&1; then
      echo "==> python: pytest"
      python -m pytest -q && ran=1 || exit 1
    else
      skip_cmd "python" "pytest"
    fi
  else
    skip_cmd "python" "python"
  fi
fi

if (( has_swift == 1 )); then
  if have_cmd swift; then
    echo "==> swift: swift test"
    swift test && ran=1 || exit 1
  else
    skip_cmd "swift" "swift"
  fi
fi

if (( has_rust == 1 )); then
  if have_cmd cargo; then
    echo "==> rust: cargo test"
    cargo test && ran=1 || exit 1
  else
    skip_cmd "rust" "cargo"
  fi
fi

if (( ${#sh_files[@]} > 0 )); then
  if have_cmd shellcheck; then
    echo "==> bash: shellcheck"
    shellcheck "${sh_files[@]}" && ran=1 || exit 1
  else
    skip_cmd "bash" "shellcheck"
  fi
fi

if (( ${#bicep_files[@]} > 0 )); then
  if have_cmd az; then
    echo "==> bicep: az bicep lint"
    for bicep_file in "${bicep_files[@]}"; do
      az bicep lint -f "$bicep_file" && ran=1 || exit 1
    done
  elif have_cmd bicep; then
    echo "==> bicep: bicep lint"
    for bicep_file in "${bicep_files[@]}"; do
      bicep lint "$bicep_file" && ran=1 || exit 1
    done
  else
    skip_cmd "az/bicep" "az/bicep"
  fi
fi

if [[ "$ran" -eq 0 ]]; then
  echo "WARN: No known test/build targets detected. Add checks to .zed/scripts/verify."
fi

echo "==> verify: OK"
SH
  chmod +x "$ZED_SCRIPTS_DIR/verify"

  # --- .zed/tasks.json ---
  cat > "$root/.zed/tasks.json" <<JSON
[
  {
    "label": "verify",
    "command": "./${VERIFY_REL}"
  },
  {
    "label": "git status",
    "command": "git status -sb"
  },
  {
    "label": "git diff",
    "command": "git diff"
  }
]
JSON
fi

echo "Initialized AgentOps scaffold in: $root"
echo "Next:"
echo "  - Open $root in Zed"
