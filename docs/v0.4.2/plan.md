# Implementation Plan: 0.4.2 optimize .rules, zed-agentops-init.sh, and README*

## 0.4.2 Positioning
- Ensure MCP server behavior and tooling guidance are aligned.
- Optimize `.rules` and `zed-agentops-init.sh` for transaction-aware task management.
- Refresh README* to match Python implementation and usage guidance.

## Objectives
- Align `.rules` and `zed-agentops-init.sh` with MCP server behavior.
- Update README.md / README-jp.md to be accurate and complete.
- Maintain test coverage >= 90%.

## Scope

### In scope
- `.rules` optimization for transaction-aware workflows and resumability.
- `zed-agentops-init.sh` correctness and consistency with MCP server behavior.
- README.md and README-jp.md updates to reflect actual runtime behavior and usage.
- Tests/coverage adjustments if required by changes.

### Out of scope
- New features unrelated to alignment/optimization.
- Large-scale refactors in runtime code not needed for alignment.

---

## 1) Problem Statement (Normalized)
- Implementation in `src/agentops_mcp_server/*.py` has advanced, while `.rules` and `zed-agentops-init.sh` may not fully leverage or reflect these behaviors.
- README* may describe behaviors or setup steps that diverge from the current codebase.
- Alignment is required to avoid mismatches between docs, scripts, and runtime behavior.

---

## 2) Design Principles (0.4.2)
1. **Source of truth alignment**
   - `.rules`, `zed-agentops-init.sh`, and README* must reflect the actual MCP server behavior.
2. **Minimal safe change**
   - Adjust only what is needed for correctness and clarity.
3. **Resumability-first**
   - Preserve and reinforce transaction-aware patterns and recovery steps.
4. **Coverage preservation**
   - Keep overall test coverage >= 90%.

---

## 3) Target Changes

### 3.1 `.rules` optimization
- Review for outdated or incomplete instructions.
- Ensure transaction-aware workflow steps match the MCP server implementation.
- Clarify required order of operations, logging, and persistence rules.
- Remove or adjust instructions that no longer match runtime behavior.

### 3.2 `zed-agentops-init.sh` alignment
- Verify it initializes environment and paths consistent with README* guidance.
- Ensure it invokes MCP server with correct options or expectations.
- Update script comments or behavior to match `.rules` and runtime design.

### 3.3 README updates (English/Japanese)
- Update setup/usage instructions to match actual behavior.
- Ensure examples (configuration, commands, environment variables) are accurate.
- Clarify any prerequisites or operational caveats.

### 3.4 Tests and coverage
- Update or add tests only if changes affect behavior.
- Maintain or improve coverage to stay >= 90%.

---

## 4) Phases & Tasks

### Phase 1: Analysis & Planning
- **p1-t1**: Inventory mismatches between `.rules`, `zed-agentops-init.sh`, README*, and `src/`.
- **p1-t2**: Draft plan for `.rules` and README updates aligned with code.

### Phase 2: Implementation
- **p2-t1**: Update `.rules` to reflect current transaction-aware workflow.
- **p2-t2**: Align `zed-agentops-init.sh` behavior and guidance.
- **p2-t3**: Update README.md and README-jp.md for correctness.

### Phase 3: Tests
- **p3-t1**: Update tests if required by any behavioral or documented changes.
- **p3-t2**: Validate coverage remains >= 90%.

### Phase 4: Verification & Release
- **p4-t1**: Run verification suite.
- **p4-t2**: Confirm acceptance criteria.

---

## 5) Acceptance Criteria
- `.rules` aligns with MCP server behavior and transaction-aware workflow.
- `zed-agentops-init.sh` matches intended usage and guidance.
- README.md and README-jp.md are accurate and consistent with runtime code.
- Test coverage >= 90% and tests pass.

---

## 6) Risks & Mitigations
- **Risk:** Hidden behavior differences between scripts and runtime code.
  - **Mitigation:** Cross-check actual runtime flow and update scripts/docs accordingly.
- **Risk:** Documentation drift in multilingual files.
  - **Mitigation:** Apply parallel updates to both README files.

---

## 7) Deliverables
- `docs/v0.4.2/plan.md`
- `docs/v0.4.2/tickets_list.json`
- `docs/v0.4.2/pX-tY.json` tickets
- Updated `.rules`, `zed-agentops-init.sh`, `README.md`, `README-jp.md`
- Any updated tests required for alignment