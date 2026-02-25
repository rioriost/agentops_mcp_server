# Handoff

## Current goal
- Ensure the Zed init script is included in the wheel and installed as an executable.

## Decisions
- Standardize MCP tool names on snake_case; dotted names are supported only as aliases for compatibility.

## Changes since last session
- `src/agentops_mcp_server/zed-agentops-init.sh`: updated `.rules` template to use `repo_commit` and `session_log_append` MCP tool names.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.
2. Reinstall the Homebrew package and verify `zed-agentops-init` appears in `bin`.
3. Decide whether to add or ignore `.agent/`, `.envrc`, `.rules`, `.gitignore`.
