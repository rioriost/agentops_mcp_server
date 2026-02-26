#!/usr/bin/env bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <root>"
  exit 1
fi
root="$1"
mkdir -p "$root"
if [ ! -d "$root/.git" ]; then
  ( cd "$root" && git init )
fi

ZED_DIR="$root/.zed"
ZED_SCRIPTS_DIR="$ZED_DIR/scripts"
AGENT_DIR="$root/.agent"
GITIGNORE_FILE="$root/.gitignore"
VERIFY_REL=".zed/scripts/verify"
HANDOFF_REL=".agent/handoff.md"
GITIGNORE_ENTRIES=(
  ".zed/"
  ".venv/"
  "__pycache__/"
  "*.py[cod]"
  ".pytest_cache/"
  ".DS_Store"
  ".envrc"
)

mkdir -p "$ZED_SCRIPTS_DIR" "$AGENT_DIR"

# --- .gitignore ---
if [ ! -f "$GITIGNORE_FILE" ]; then
  touch "$GITIGNORE_FILE"
fi
append_gitignore_entry() {
  local entry="$1"
  if ! grep -qxF "$entry" "$GITIGNORE_FILE"; then
    echo "$entry" >> "$GITIGNORE_FILE"
  fi
}
for entry in "${GITIGNORE_ENTRIES[@]}"; do
  append_gitignore_entry "$entry"
done

# --- .rules ---
cat > "$root/.rules" <<'RULES'
# AgentOps (project rules)
# Goal: Max automation for (1) cross-session handoff, (2) verify->commit loop, (3) test generation.

## Always do this at the start
- Read ${HANDOFF_REL} and restate:
  - Current goal
  - Next actions
  - Last verification status

## Work loop (mandatory)
- For any code change:
  1) Implement smallest safe change
  2) Run "${VERIFY_REL}"
  3) If it fails: fix and repeat
  4) If it passes: commit changes
  5) Update handoff

## Handoff is source of truth
- ${HANDOFF_REL} must be updated after:
  - verify success
  - commit
  - session end
- Write concise, actionable content:
  - Decisions, Changes, Verification, Next actions

## Commit message
- ~80 chars, semantic summary (not strict conventional commits)
- Mention scope if useful (e.g. "rust:", "py:", "swift:", "infra:")

## Prefer MCP tools if available
- If MCP tools exist:
  - use mcp:agentops:handoff_update to update handoff
  - use mcp:agentops:repo_commit to commit after verify
  - use mcp:agentops:session_log_append to store session logs
- Otherwise:
  - update ${HANDOFF_REL} directly

## MCP workspace_root requirement
- When calling MCP tools, always pass `workspace_root` (project root path).
- If `workspace_root` is omitted, the server falls back to its current working directory.
RULES

# --- initial handoff.md ---
cat > "$AGENT_DIR/handoff.md" <<'MD'
# Handoff

## Current goal
- (fill)

## Decisions
- (fill)

## Changes since last session
- (fill)

## Verification status
- Last verify: (never)

## Next actions
1. (fill)
MD

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

bicep_files=()
sh_files=()
has_python=0
has_swift=0
has_rust=0

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
    *.bicep) bicep_files+=("$path") ;;
    *.sh) sh_files+=("$path") ;;
  esac
done

ran=0

if (( has_python == 1 )); then
  if command -v python >/dev/null 2>&1; then
    if python -m pytest --version >/dev/null 2>&1; then
      echo "==> python: pytest"
      python -m pytest -q && ran=1 || exit 1
    else
      echo "==> python: pytest not installed; skipping"
    fi
  fi
fi

if (( has_swift == 1 )); then
  if command -v swift >/dev/null 2>&1; then
    echo "==> swift: swift test"
    swift test && ran=1 || exit 1
  fi
fi

if (( has_rust == 1 )); then
  if command -v cargo >/dev/null 2>&1; then
    echo "==> rust: cargo test"
    cargo test && ran=1 || exit 1
  fi
fi

# Optional: bicep lint if az or bicep exists
if (( ${#bicep_files[@]} > 0 )); then
  if command -v az >/dev/null 2>&1; then
    echo "==> bicep: az bicep lint"
    for bicep_file in "${bicep_files[@]}"; do
      az bicep lint -f "$bicep_file" && ran=1 || exit 1
    done
  elif command -v bicep >/dev/null 2>&1; then
    echo "==> bicep: bicep lint"
    for bicep_file in "${bicep_files[@]}"; do
      bicep lint "$bicep_file" && ran=1 || exit 1
    done
  else
    echo "==> bicep: az/bicep not installed; skipping"
  fi
else
  echo "==> bicep: no .bicep changes; skipping"
fi

# Optional: bash lint if shellcheck exists
if command -v shellcheck >/dev/null 2>&1; then
  if (( ${#sh_files[@]} > 0 )); then
    echo "==> bash: shellcheck"
    shellcheck "${sh_files[@]}" && ran=1 || exit 1
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

echo "Initialized AgentOps scaffold in: $root"
echo "Next:"
echo "  - Open $root in Zed"
