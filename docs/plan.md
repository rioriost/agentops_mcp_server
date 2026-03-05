# Implementation Plan: Pass CWD as workspace_root

## Objectives
- Update `.rules` to instruct passing CWD as `workspace_root`.
- Avoid ambiguity in `workspace_root` usage.

## Assumptions
- MCP server runs with CWD set to repository root.
- The rule change is documentation-only.

## Phases

### Phase 1: Update rules
**Goals**
- Make the rule explicit about using CWD for `workspace_root`.

**Tasks**
- Edit `.rules` to say “Always pass CWD as workspace_root to MCP tools.”

---

### Phase 2: Verification
**Goals**
- Ensure the rule text is correct and unambiguous.

**Tasks**
- Review `.rules` for the updated wording.

## Acceptance Criteria Mapping
- `.rules` clearly instructs using CWD as `workspace_root`.
- No other behavior changes are introduced.