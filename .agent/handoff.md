# Handoff

## Current goal
- Skip overwriting existing .gitignore, .rules, .agent/handoff.md, and .zed scaffold assets when initializing into an existing directory.

## Decisions
- Treat existing paths as non-overwritable, emitting skip messages instead of clobbering files.

## Changes since last session
- `src/agentops_mcp_server/zed-agentops-init.sh`: guard existing .gitignore/.rules/handoff; skip .zed scaffold if present; handle non-file/non-dir paths with skip notices.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Review the greenfield remote plan in `revise_plan.md` and confirm scope/capabilities.
2. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.
