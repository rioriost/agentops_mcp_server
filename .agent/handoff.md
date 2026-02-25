# Handoff

## Current goal
- Ensure the Zed init script is included in the wheel and installed as an executable.

## Decisions
- Use wheel `include` to bundle `src/agentops_mcp_server/zed-agentops-init.sh`.

## Changes since last session
- `pyproject.toml`: added wheel `include` for `src/agentops_mcp_server/zed-agentops-init.sh` and removed shared-scripts/shared-data/force-include.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.
2. Reinstall the Homebrew package and verify `zed-agentops-init` appears in `bin`.
3. Decide whether to add or ignore `.agent/`, `.envrc`, `.rules`, `.gitignore`.