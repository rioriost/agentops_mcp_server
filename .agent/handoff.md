# Handoff

## Current goal
- Switch WIP tracking to JSON and initialize `.agent/work-in-progress.json` during init.

## Decisions
- Keep `handoff.md` in Markdown while using JSON for WIP state.

## Changes since last session
- `src/agentops_mcp_server/zed-agentops-init.sh`: update `.rules` WIP section for JSON fields; create `work-in-progress.json` on init.

## Verification status
- Last verify: `.zed/scripts/verify` (OK; no tests detected).

## Next actions
1. Review the greenfield remote plan in `revise_plan.md` and confirm scope/capabilities.
2. Build a wheel and confirm it contains `agentops_mcp_server/zed-agentops-init.sh`.
