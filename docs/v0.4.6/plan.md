# Implementation Plan: 0.4.6 Multiple MCP Servers with Zed

## 0.4.6 Positioning
- This release addresses a compatibility issue between `agentops_mcp_server` and Zed when multiple projects are open at the same time.
- The issue is triggered by Zed launching additional MCP server processes with `CWD="/"` in some multi-project cases.
- The selected workaround is to bind the project root exactly once during session startup via a dedicated workspace initialization step, instead of relying on ambient process cwd.
- The release must preserve the 0.4.3 safety goal: never resolve project artifacts to `/.agent/`.

## Objectives
- Allow `agentops_mcp_server` to start under Zed even when the host process working directory is `"/"`.
- Introduce a one-time `workspace_initialize(cwd)` binding flow that establishes the canonical project root for the server session.
- Preserve safe artifact path resolution so read/write operations never target `/.agent/`.
- Add persistent tool error logging so failed tool executions are recorded in `.agent/errors.jsonl` with tool name, input, and output/error details.
- Update `.rules` and the `zed-agentops-init.sh` heredoc so the startup contract requires workspace initialization before state restore.
- Reach and maintain test coverage >= 90%.

## Scope

### In scope
- Runtime handling for startup when `Path.cwd()` resolves to `"/"`.
- A dedicated one-time workspace initialization tool and root-binding lifecycle.
- Persistent error logging for failed tool executions under `.agent/errors.jsonl`.
- Startup-rule updates in `.rules` and scaffold updates in `zed-agentops-init.sh`.
- Updates to runtime code, docs, and tests required by the new initialization contract.

### Out of scope
- Fixing Zed itself.
- Broad redesign of transaction/state artifacts unrelated to project-root initialization.
- Unrelated feature work.

---

## 1) Problem Statement (Normalized)
Current behavior after 0.4.3:
- `RepoContext` rejects `repo_root="/"` at startup.
- This prevents accidental expansion of artifact paths such as `/.agent/tx_state.json`.

Observed interoperability issue:
- In Zed multi-project scenarios, additional MCP server processes may start with `CWD="/"`.
- As a result, the Python MCP server fails to boot for the second and later projects, even though each project should have its own server instance.

Historical risk that must not regress:
- Before the 0.4.3 guard, artifact paths could be resolved relative to `"/"`, causing writes such as `/.agent/...` and resulting permission errors or unsafe behavior.

Additional product constraint:
- In Zed, one MCP server instance maps to one project directory.
- That project directory is stable for the lifetime of the server session.
- Therefore, project-root binding can be done once at startup/initialization time and reused for the remainder of the session.

Design tension:
- Rejecting `"/"` at process startup is safe but breaks multi-project Zed usage.
- Blindly accepting `"/"` restores startup but reintroduces unsafe artifact resolution.
- The release needs a middle-ground design that tolerates broken host startup context while enforcing a one-time validated project-root bind before any file-backed operation.

---

## 2) Design Principles (0.4.6)

1. **Safe by default**
   - Never allow canonical or derived artifacts to be read from or written to `/.agent/`.

2. **One-time explicit binding**
   - The canonical project root should be established once through `workspace_initialize(cwd)` and then retained for the session.

3. **Host-bug tolerance**
   - The MCP server should degrade gracefully around Zed’s `CWD="/"` bug instead of failing immediately.

4. **Initialization before restore**
   - Workspace binding must occur before reading `tx_state`, `tx_event_log`, or `handoff`.

5. **Single-project session invariant**
   - One server process corresponds to one project root; rebinding to a different root is invalid.

6. **Minimal surface change**
   - Keep the fix narrowly targeted to initialization, root binding, and affected file-backed tools.

7. **Operational observability**
   - Failed tool executions should be recorded as structured local artifacts so they can be inspected after the fact, not only in the Zed agent panel.

8. **Coverage preservation**
   - Add deterministic tests for startup under `"/"`, successful initialization, rejection of unsafe or conflicting roots, and error-log persistence.

---

## 3) Selected Approach

### Rejected: keep startup failure on `"/"`
- Safe, but does not solve the release goal.

### Rejected: accept `"/"` globally and keep using ambient cwd
- Restores startup, but reintroduces the exact unsafe path expansion that 0.4.3 fixed.

### Selected: start unresolved, then bind once with `workspace_initialize(cwd)`
- Allow the server to start even when process cwd is `"/"`.
- Keep the repo context unresolved until initialization.
- Require a one-time `workspace_initialize(cwd)` call that validates and binds the project root.
- Reject root-dependent operations until binding is complete.
- Preserve backward compatibility by allowing implicit binding from a non-`"/"` startup cwd in normal single-project launches.

Why this is preferred:
- Matches Zed’s project model: one server instance, one stable directory.
- Avoids pushing `cwd` through every tool call.
- Preserves strict safety around `/.agent/`.
- Works naturally with `.rules` as a mandatory startup step.

---

## 4) Proposed Design

## 4.1 Runtime startup model
- Replace unconditional `RepoContext(Path.cwd().resolve())` failure on `"/"` with a startup mode that can exist without a validated project root.
- If `Path.cwd().resolve()` is not `"/"`, the server may bind that root immediately for backward compatibility.
- If `Path.cwd().resolve()` is `"/"`, the server starts in an unresolved state and waits for `workspace_initialize(cwd)`.

## 4.2 New startup binding tool
Introduce a dedicated tool:

- `workspace_initialize(cwd)`

Expected behavior:
- Resolve and validate `cwd`.
- Reject `cwd == "/"`.
- If no root is currently bound, bind it and return success.
- If the same root is already bound, treat the call as a no-op success.
- If a different root is already bound, reject the call.

Expected result shape:
- `ok`
- `repo_root`
- `initialized`
- `changed`

This tool becomes the required first step in `.rules` startup flow.

## 4.3 Repo root lifecycle
The repo context must explicitly represent:

- **unresolved**
  - no validated project root has been bound yet
- **resolved**
  - a validated non-root project path is bound for the session

Allowed transitions:
- unresolved -> resolved: allowed through startup implicit bind or `workspace_initialize(cwd)`
- resolved -> resolved with same path: allowed as no-op
- resolved -> resolved with different path: rejected

## 4.4 Root-dependent operations
Any operation that touches:
- repository commands,
- `.agent` artifacts,
- `.zed/scripts/verify`,
- or filesystem-backed state/log files

must require a bound validated repo root before proceeding.

If root is not initialized:
- fail with a clear message instructing the caller to run `workspace_initialize(cwd)` first.

Examples of affected tools/components:
- `tx_event_append`
- `tx_state_save`
- `tx_state_rebuild`
- `repo_verify`
- `repo_commit`
- `repo_status_summary`
- `session_capture_context`
- `ops_*` tools that read/write artifacts
- underlying repo/state/verify helpers

## 4.5 Safety validation rules
A bound root must satisfy:
- it is not `"/"`,
- artifact paths derived from it do not point to `/.agent/...`,
- repo-specific operations consistently use that bound root.

Additional guard:
- even if a caller explicitly passes `"/"` to `workspace_initialize(cwd)`, reject it.

## 4.6 Tool error logging
Add a persistent local error log artifact:

- `.agent/errors.jsonl`

Logging requirements:
- Append one structured JSON line for each failed tool execution.
- At minimum, record:
  - tool name
  - tool input
  - tool output/error
  - timestamp
- Prefer capturing failures at the JSON-RPC tool execution boundary so both validation failures and runtime failures are included.
- Logging failure details must not prevent the original tool error from being returned to the client.
- Error logging must use the initialized project root and must never write to `/.agent/errors.jsonl`.

Expected use:
- Provide a durable local error trail that can be inspected after the session.
- Complement, not replace, the error display shown in the Zed agent panel.

## 4.7 `.rules` and scaffold contract
The startup contract must change from:

1. tx_state
2. tx_event_log
3. handoff

to:

1. `workspace_initialize(cwd)`
2. tx_state
3. tx_event_log
4. handoff

This must be reflected in:
- repository `.rules`
- the `.rules` heredoc embedded in `src/agentops_mcp_server/zed-agentops-init.sh`

The wording should make clear:
- initialization is mandatory,
- it must happen once,
- it must happen before reading canonical state,
- root-dependent tools must not run before initialization is complete.

## 4.8 Backward compatibility
- Preserve current behavior for normal single-project launches where cwd is already the project root.
- In those cases, startup may bind immediately and `workspace_initialize(cwd)` may be a no-op if called with the same root.
- The new explicit initialization path is primarily for the Zed multi-project case where process cwd is `"/"`.

---

## 5) Target Changes

### 5.1 `src/agentops_mcp_server/repo_context.py`
- Redesign repo-root handling to support unresolved startup state.
- Add explicit root-binding behavior for one-time initialization.
- Add invariant checks for:
  - unresolved access,
  - rejecting `"/"`,
  - rejecting conflicting rebinds.
- Ensure artifact path helpers still reject unsafe root usage.

### 5.2 `src/agentops_mcp_server/main.py`
- Stop assuming `Path.cwd().resolve()` is always a valid repo root at import/startup.
- Initialize runtime components so they can exist before root binding completes.
- Preserve implicit bind behavior for normal non-root cwd startup.

### 5.3 Tool registration and routing
- Add `workspace_initialize(cwd)` to the exposed tool set.
- Route initialization requests to the repo-context binding logic.
- Ensure root-dependent tools fail clearly when called before initialization.

### 5.4 Root-dependent runtime components
Review and update:
- `state_store.py`
- `state_rebuilder.py`
- `repo_tools.py`
- `verify_runner.py`
- `git_repo.py`
- `commit_manager.py`
- `ops_tools.py`
- `tool_router.py`

Expected changes:
- require bound root before filesystem/repo actions,
- use the bound root consistently,
- emit clear errors when initialization is missing.

### 5.5 Error logging pipeline
Review and update:
- `json_rpc_server.py`
- `repo_context.py`
- `state_store.py`

Expected changes:
- add an artifact path for `.agent/errors.jsonl`,
- append one structured JSON record per failed tool execution,
- capture tool name, input, and output/error at the tool-call boundary,
- ensure error logging is best-effort and does not mask the original client-facing failure.

### 5.6 `.rules`
- Update the root `.rules` file to require `workspace_initialize(cwd)` first in `## Start (mandatory)`.
- Clarify that canonical state restore occurs only after initialization.
- Clarify that root-dependent tools must not run before initialization.

### 5.7 `src/agentops_mcp_server/zed-agentops-init.sh`
- Update the embedded `.rules` heredoc to match the new startup contract.
- Keep the scaffolded `.rules` output in sync with the repository copy.

### 5.8 Documentation
Update release-facing docs to explain:
- why the change exists,
- how the one-time initialization binding works,
- how Zed multi-project launches interact with the server,
- the safety guarantee that `/.agent/` is never used as a project artifact root,
- and that failed tool executions are persisted in `.agent/errors.jsonl`.

---

## 6) Phases & Tasks

### Phase 1: Design and contract update
- **p1-t1**: Finalize the `workspace_initialize(cwd)` startup contract and repo-root binding invariants.
- **p1-t2**: Update `.rules` and `zed-agentops-init.sh` heredoc design requirements to reflect initialization-before-restore.

### Phase 2: Runtime implementation
- **p2-t1**: Refactor `RepoContext` and startup wiring to support unresolved startup and one-time root binding.
- **p2-t2**: Implement `workspace_initialize(cwd)` and register it in the tool layer.
- **p2-t3**: Update root-dependent operations to require initialized root and fail clearly otherwise.
- **p2-t4**: Implement persistent `.agent/errors.jsonl` logging for failed tool executions.

### Phase 3: Tests
- **p3-t1**: Add unit tests for unresolved startup, successful initialization, same-root reinitialization, and conflicting rebind rejection.
- **p3-t2**: Add runtime/tool tests for root-dependent operations before and after initialization, including `CWD="/"` startup behavior.
- **p3-t3**: Add tests for failed tool execution logging, including tool name, input, and output/error capture.
- **p3-t4**: Run coverage-focused verification and close any gaps to maintain >= 90%.

### Phase 4: Documentation and verification
- **p4-t1**: Update documentation for one-time workspace initialization, Zed multi-project behavior, and local error-log artifacts.
- **p4-t2**: Run verification suite and confirm acceptance criteria.

---

## 7) Acceptance Criteria
- `agentops_mcp_server` can start under Zed multi-project scenarios even when process cwd is `"/"`.
- The server supports a one-time `workspace_initialize(cwd)` flow that binds the canonical project root for the session.
- `workspace_initialize(cwd)` rejects `"/"` and rejects rebinding to a different project root.
- Root-dependent tool calls do not read from or write to `/.agent/`.
- Root-dependent tool calls fail clearly before initialization when startup cwd is unresolved.
- Failed tool executions are appended to `.agent/errors.jsonl` with tool name, input, and output/error details.
- Existing normal project-root launches continue to work.
- `.rules` and the `zed-agentops-init.sh` scaffolded heredoc both reflect the new startup contract.
- Test coverage >= 90% and verification passes.

---

## 8) Risks & Mitigations

### Risk: AI agents do not reliably follow the new startup instruction
- **Mitigation:** enforce the rule in runtime by rejecting root-dependent operations before initialization, with explicit guidance to call `workspace_initialize(cwd)`.

### Risk: `.rules` and scaffolded `.rules` diverge
- **Mitigation:** update both the repository `.rules` file and the `zed-agentops-init.sh` heredoc in the same change and add tests if practical.

### Risk: Hidden root assumptions remain in runtime code
- **Mitigation:** enumerate all root-dependent paths first and add targeted tests for each affected component.

### Risk: Error logging captures too little or too much data
- **Mitigation:** define a minimal structured schema for `.agent/errors.jsonl` that captures actionable tool context without dumping unnecessary payloads beyond tool name, input, output/error, and timestamp.

### Risk: Startup succeeds but operations fail unexpectedly
- **Mitigation:** provide explicit, actionable error messages for uninitialized-root cases and cover them with tests.

### Risk: Safety regression reintroduces writes to `/.agent/`
- **Mitigation:** keep hard validation in root binding, artifact-path creation, and error-log path resolution, plus negative tests specifically for `"/"`.

### Risk: Reinitialization behavior becomes ambiguous
- **Mitigation:** define strict semantics: same-root reinit is no-op success; different-root reinit is error.

---

## 9) Deliverables
- `docs/v0.4.6/plan.md`
- `docs/v0.4.6/pX-tY.json` tickets
- Updated runtime files under `src/agentops_mcp_server/`
- Updated `.rules`
- Updated `src/agentops_mcp_server/zed-agentops-init.sh`
- New `.agent/errors.jsonl` runtime artifact support
- Updated tests under `tests/`
- Any necessary README documentation updates