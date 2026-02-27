# Handoff

## Current goal
- Ensure the Zed init script is included in the wheel and installed as an executable.

## Decisions
- Unify command availability checks in `.zed/scripts/verify` to avoid repeated logic.

## Changes since last session
- `src/agentops_mcp_server/zed-agentops-init.sh`: `.zed/scripts/verify` now uses shared command-check helpers and only reports missing tools when relevant.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Pass `workspace_root` in MCP tool calls and confirm `.agent`/`.zed` paths resolve correctly.
2. Review the greenfield remote plan in `revise_plan.md` and confirm scope/capabilities.
3. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.