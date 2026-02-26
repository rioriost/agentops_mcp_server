# Greenfield Remote MCP Server Design Plan

## Summary
Design and implement a remote-first MCP server that provides the same functional surface as the current local server (handoff, verify, repo status, session logs, checkpoints, test suggestions) without assuming access to the client filesystem or local process execution. All file and command operations are performed by a client-side executor over explicit, authenticated protocols.

## Goals
- Provide the same tool capabilities as the local MCP server.
- Run entirely remote: no direct access to client files or local commands.
- Ensure secure, auditable, and explicit execution of file and command operations.
- Keep the design transport-agnostic (stdio, HTTP, WebSocket).

## Non-Goals
- Transparent remote filesystem mirroring.
- Implicit or ambient access to client resources.

## Architecture Overview
### Components
1. **Remote MCP Server**
   - Exposes tools via MCP JSON-RPC.
   - Holds session state and validates requests.
   - Delegates all file/command operations to a client executor.

2. **Client Executor (Required)**
   - Runs on the user's machine or within the target workspace.
   - Implements filesystem and command APIs.
   - Enforces local security policy and user consent.

3. **Transport Layer**
   - MCP-compatible JSON-RPC over stdio or network.
   - Optional secure channel (mTLS, SSH, or signed tokens).

### Trust Boundary
- Server is untrusted with respect to local files.
- Client executor is the sole authority for local operations.

## Core Abstractions
### Workspace API (implemented by client executor)
- `workspace.read(path)`
- `workspace.write(path, content)`
- `workspace.list(path)`
- `workspace.stat(path)`
- `workspace.run(command, cwd, timeout)`
- `workspace.cwd()`
- `workspace.root()` (optional explicit root)

### Server Tool Surface
- `handoff_read`
- `handoff_update`
- `handoff_normalize`
- `repo_verify`
- `repo_status_summary`
- `repo_commit`
- `session_log_append`
- `session_checkpoint`
- `session_diff_since_checkpoint`
- `tests_suggest`
- `tests_suggest_from_failures`

## Data Model
### Workspace Context
- `workspace_root` (required)
- `workspace_id` (optional)
- `capabilities` (read/write/run)

### Audit Log
Each server request records:
- tool name
- resolved workspace path
- command (if any)
- timestamp
- result status

## Request Flow (Remote-First)
1. Client connects and provides `workspace_root` and `capabilities`.
2. Server validates workspace and stores session context.
3. Server tools resolve paths relative to `workspace_root`.
4. Server calls `workspace.*` methods via the executor.
5. Executor performs the action and returns results.
6. Server returns tool output.

## Tool Behavior Details
### Handoff Tools
- `handoff_read`: `workspace.read(".agent/handoff.md")`
- `handoff_update`: `workspace.write(".agent/handoff.md", content)`
- `handoff_normalize`: read → normalize → write

### Verify and Repo Tools
- `repo_verify`: `workspace.run(".zed/scripts/verify", cwd=workspace_root)`
- `repo_status_summary`: execute `git` commands via `workspace.run`

### Session Logs and Checkpoints
- `.agent/session-log.jsonl`: append via `workspace.write` with read-modify-write or executor-supported append.
- `.agent/checkpoints/*.json`: write checkpoint snapshots via executor.

## Security Model
- Path normalization and traversal protection enforced by executor.
- Command execution restricted to an allowlist (`git`, `.zed/scripts/verify`, etc).
- Optional interactive approval on client side.
- Request signing or token authentication for remote calls.

## Implementation Plan (Greenfield)
### Phase 1: Protocol and Interfaces
- Define `workspace.*` RPC schema and error contract.
- Define server tool schema and required context.
- Implement a reference client executor.

### Phase 2: Remote MCP Server
- Implement tool handlers using only `workspace.*` calls.
- Add session context validation for `workspace_root`.
- Add structured audit logging.

### Phase 3: Client Executor
- Local filesystem operations with sandboxing to `workspace_root`.
- Safe command runner with allowlist and timeouts.
- Optional user consent UI for write/run.

### Phase 4: Integration & Docs
- End-to-end demo with Zed client executor.
- Document deployment patterns (local executor, SSH tunnel, hosted server).

## Open Questions
- How to propagate user consent for write/run across repeated commands?
- Should executor support streaming stdout/stderr?
- What is the default allowlist for `workspace.run`?

## Success Criteria
- Full tool parity with local MCP server without server-side filesystem access.
- Verified remote `handoff_read`, `repo_verify`, and `repo_status_summary`.
- Clear security boundaries and auditable actions.
