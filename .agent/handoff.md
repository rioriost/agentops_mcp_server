# Handoff

## Current goal
- Ensure the Zed init script is included in the wheel and installed as an executable.

## Decisions
- Expose only structured handoff tool and alias legacy name in calls to avoid OpenAI tool-name collisions.

## Changes since last session
- `src/agentops_mcp_server/main.py`: removed legacy `handoff_update` from tool registry and aliased calls to `handoff.update` to avoid `_2` tool names.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.
2. Reinstall the Homebrew package and verify `zed-agentops-init` appears in `bin`.
3. Decide whether to add or ignore `.agent/`, `.envrc`, `.rules`, `.gitignore`.
