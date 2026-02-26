# Remote-Capable Redesign Plan (MCP Server)

## Summary
Current design assumes local filesystem access (`.agent/`, `.zed/`, repo root) and local process execution (`git`, `verify`). In a remote deployment, these assumptions fail because the server cannot read/write local project files or execute local commands. This plan redesigns the MCP server to operate in remote environments by making all file/system interactions explicit, client-driven, and optionally bridged through a secure agent on the client side.

## Goals
- Run MCP server remotely without direct access to client filesystem.
- Preserve tool capabilities (handoff, verify, repo status) via explicit client mediation.
- Maintain backward compatibility for local deployments.

## Non-Goals
- Building a full remote IDE sync system.
- Implicitly accessing client files without explicit transport.

## Key Design Changes

### 1. Introduce a "Workspace Provider" Abstraction
Add a pluggable interface used by all file and repo operations:

- `read_file(path)`
- `write_file(path, content)`
- `list_directory(path)`
- `run_command(command, cwd)`
- `stat(path)` / `exists(path)`
- `cwd()` (optional)

Two implementations:
1. **LocalWorkspaceProvider**: current behavior using local FS + subprocess.
2. **RemoteWorkspaceProvider**: delegates operations to the MCP client via new tool calls or a relay protocol.

### 2. Explicit Workspace Context
Remove implicit `REPO_ROOT = Path.cwd().resolve()` assumptions.

- Add a required `workspace_root` field for tools that need repo context.
- Store the current workspace root in session state (set via `initialize` or a new tool).
- Reject operations if `workspace_root` is missing.

### 3. Client-Mediated File Operations
Define new MCP tool calls that the client implements (or proxy agent implements):

- `workspace.read`
- `workspace.write`
- `workspace.list`
- `workspace.run`
- `workspace.stat`

Server-side tool handlers call these instead of local FS.  
For local mode, these calls are implemented by LocalWorkspaceProvider.

### 4. Handoff Handling
Handoff is now stored via provider:

- `handoff_read` → `workspace.read(".agent/handoff.md")`
- `handoff_update` → `workspace.write(".agent/handoff.md", content)`

If remote mode and file doesn’t exist, create it via `workspace.write`.

### 5. Verify/Repo Commands
Replace direct `subprocess` and `git` with provider-backed `workspace.run`.

- `repo_verify` runs `.zed/scripts/verify` via `workspace.run`.
- `repo_status_summary` runs `git` commands via `workspace.run`.

### 6. Session Log & Checkpoints
Session log and checkpoints are written via provider:

- `.agent/session-log.jsonl`
- `.agent/checkpoints/*.json`

### 7. Backward Compatibility
Default to LocalWorkspaceProvider when:
- `REMOTE_WORKSPACE=0` or unset.
- `workspace_root` is inferred from `cwd` (local mode only).

Remote mode requires explicit `workspace_root` and provider implementation.

## Data Flow

1. Client connects, passes `workspace_root` and mode (local/remote).
2. Server stores workspace context in session state.
3. Tool calls resolve file paths relative to `workspace_root`.
4. All file/command operations go through the provider.

## Security Considerations
- Validate and normalize paths to prevent traversal outside `workspace_root`.
- Restrict `workspace.run` to whitelisted commands or approved scripts.
- Require explicit client consent for writes and command execution.
- Log all remote operations for auditability.

## Migration Plan

1. **Phase 1: Abstraction Layer**
   - Add provider interface.
   - Refactor all file and command usages to go through provider.
   - Keep local behavior unchanged.

2. **Phase 2: Remote Provider**
   - Define new client-side MCP tools.
   - Implement remote provider calling these tools.

3. **Phase 3: Workspace Context**
   - Require `workspace_root` for remote mode.
   - Add explicit errors when missing.

4. **Phase 4: Documentation**
   - Update README with local vs remote usage.
   - Document required client integrations.

## Open Questions
- Should `workspace_root` be a mandatory param for all repo tools?
- Do we need a capability handshake to confirm remote support?
- How to handle long-running commands (`verify`) in remote mode?

## Success Criteria
- Remote MCP server can read/write `handoff.md` in the client’s project.
- `repo_verify` and `repo_status_summary` work via remote command execution.
- No implicit dependency on server-local filesystem.
