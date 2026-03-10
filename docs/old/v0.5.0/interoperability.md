# AgentOps v0.5.0 Interoperability Guide

This document explains the supported client/server workflow contract for v0.5.0 in release-facing terms.

The goal of v0.5.0 is not to redesign the transaction core. The goal is to make the documented workflow, the generated scaffold, and the runtime server behavior line up clearly enough that a client implementer or operator can understand what is guaranteed by the server, what is provided as helper behavior, and what remains external workflow convention.

## Scope of this guide

This guide focuses on interoperability-critical behavior across:

- repository `.rules`
- generated scaffold from `zed-agentops-init.sh`
- runtime MCP server behavior
- client-facing helper tools
- baseline state and resume behavior
- version/reporting surfaces

It does not restate every internal detail of the transaction engine. It instead describes the contract that matters to a client integrating with the server.

## Contract summary

### What is protocol-enforced by the server

The server enforces the canonical transaction/event workflow, including:

- workspace root binding before root-dependent operations
- canonical transaction ordering
- transaction begin before task lifecycle events
- verify start before verify pass/fail
- verify pass before file intent verification
- file intent registration before file intent update for the same path
- monotonic file intent state progression
- commit gating on verified state
- no-change commit rejection
- transaction-context checks for guarded workflow operations
- canonical rebuild and integrity checking of transaction state

### What is provided as client-facing helper behavior

The server provides helper tools that wrap the canonical event/state model, including:

- task lifecycle helpers
- file intent helper operations
- verify and commit helpers
- resume, handoff, and observability helpers

These helpers are part of the supported client-facing surface, but they remain wrappers over the canonical transaction model rather than a replacement for it.

### What remains client-side operating convention

The following remain convention rather than mandatory server protocol:

- maintaining `docs/__version__/plan.md`
- maintaining `docs/__version__/tickets_list.json`
- maintaining per-ticket files like `docs/__version__/pX-tY.json`
- synchronizing client-managed planning artifacts with runtime progress

The server does not guarantee generation, persistence, synchronization, or validation of those ticket artifacts. Clients may maintain them, and doing so can be useful, but that bookkeeping is external workflow discipline.

## Canonical workflow model

## 1. Workspace initialization

Before root-dependent work, the workspace must be initialized for the current project root.

The supported model is:

1. bind the workspace root
2. read materialized transaction state
3. inspect or replay the canonical transaction event log as needed
4. treat handoff as derived-only context

The handoff artifact is not canonical state. Resume decisions should be driven by materialized state and canonical event history.

## 2. Transactions are canonical

The canonical system of record is the transaction/event model.

Important consequences:

- canonical ordering matters
- helper tools must not weaken transaction ordering guarantees
- invalid sequences are rejected rather than silently accepted
- derived summaries are not a substitute for canonical transaction state

## 3. Lifecycle model exposed to clients

The top-level lifecycle states exposed to clients are:

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

The authoritative runtime notion of lifecycle is still derived from canonical transaction state and event progression. Lifecycle helpers exist to make that contract easier to use safely.

## 4. Verify and commit

The supported workflow is:

1. make the intended change
2. run verification
3. only after a successful verify, attempt commit
4. reject commit when there is nothing to commit
5. complete the transaction

Two important enforcement points are explicit:

- commit is blocked when verify has not passed
- commit is blocked when the repository has no changes to commit

## 5. File intent workflow

The file intent model remains canonical and strict, but the client-facing workflow is now ergonomic enough for routine use without raw low-level event assembly.

Supported helper surface:

- `ops_add_file_intent`
- `ops_update_file_intent`
- `ops_complete_file_intent`

Supported workflow mapping:

- register file intent -> `ops_add_file_intent`
- mark file intent started -> `ops_update_file_intent(state="started")`
- mark file intent applied -> `ops_update_file_intent(state="applied")`
- mark file intent verified -> `ops_update_file_intent(state="verified")`
- complete verified file intent -> `ops_complete_file_intent`

These helpers still route through canonical file intent events and canonical validation.

## What is enforced vs what is documented

### Enforced behavior

The server enforces:

- begin-before-lifecycle ordering
- verify-before-verified ordering
- file-intent registration before update
- file-intent monotonic progression
- verify-pass prerequisite for verified file intents
- commit preconditions
- active transaction checks
- rebuild integrity checks

### Documented helper behavior

The server documents and supports:

- lifecycle helpers as wrappers over canonical state
- file intent helpers as wrappers over canonical file intent events
- resume/handoff helpers as convenience surfaces around canonical state interpretation
- bootstrap scaffold behavior and baseline state expectations

### Convention-only behavior

The server documents, but does not enforce as protocol:

- client-maintained ticket documents
- client-maintained plan files
- synchronization of external ticket metadata with runtime lifecycle state

## Rules, scaffold, and runtime alignment

v0.5.0 is intended to make these three layers agree:

1. the repository workflow rules
2. the initialization scaffold
3. the runtime server behavior

### Rules alignment

The repository rules are intended to describe the strict workflow contract and to distinguish protocol from convention.

### Scaffold alignment

The generated scaffold is intended to reflect the same workflow assumptions, especially around:

- canonical local artifacts
- baseline state files
- verification entry points
- resumability-related guidance

### Runtime alignment

The runtime server behavior is intended to match the same model through:

- canonical transaction validation
- strict guarded operations
- helper tools that preserve invariants
- rebuild and integrity behavior

## Bootstrap state expectations

The baseline `.agent/tx_state.json` generated by initialization is intentionally a normalized empty-transaction state.

It is designed to be compatible with runtime expectations without pretending to know facts that only canonical event replay can establish later.

The baseline includes the major fields clients normally need to reason about the state shape, including:

- `schema_version`
- `active_tx`
- `last_applied_seq`
- `integrity.state_hash`
- `integrity.rebuilt_from_seq`
- `integrity.drift_detected`
- `integrity.active_tx_source`
- `updated_at`

This reduces ambiguity between:

- "field is missing because the scaffold is old or incomplete"
- and
- "field is absent because runtime replay has not yet materialized derived facts"

## Version surfaces

Different version surfaces mean different things.

### Package/server version

This is the version of the released MCP server implementation.

It should match user-visible server reporting surfaces that identify the implementation version.

### Transaction/schema version

This is the version of the persisted transaction state structure.

It is not the same thing as the package version or a release-plan version.

### Draft/release-plan version

This is the version used by planning and release documentation under `docs/`, such as `v0.5.0`.

It describes the workflow/release line being planned or validated, not necessarily the transaction schema version.

### Why this distinction matters

If these concepts are blurred together, clients and operators can misread the system state. For example:

- a server implementation version may change without changing the transaction schema
- a release-plan version may describe a workflow alignment milestone rather than a wire-format change
- schema compatibility should not be inferred solely from release-document labels

## Supported client implementation strategy

A client that wants to interoperate safely with the v0.5.0 contract should:

1. initialize the workspace root
2. treat canonical transaction state and event history as authoritative
3. use helper tools for routine lifecycle and file intent operations
4. rely on helper rejection behavior rather than assuming invalid flows will be corrected automatically
5. treat handoff and summaries as derived guidance
6. treat plan/ticket artifacts as external workflow bookkeeping unless the client itself chooses to maintain them

## Practical workflow example

A typical safe client flow is:

1. initialize the workspace
2. inspect resume state
3. if a non-terminal transaction is active, resume it
4. if there is no active transaction, begin the next ticket
5. register file intents before mutating files
6. perform the smallest safe change
7. run verification
8. if verification passes, commit if changes exist
9. complete the transaction
10. optionally update client-managed ticket artifacts as external bookkeeping

## Interoperability guarantees for v0.5.0

For the supported v0.5.0 workflow surface, the intended guarantees are:

- workflow-critical `.rules` content and scaffold behavior are aligned
- lifecycle helpers map onto the canonical workflow model coherently
- commit gating is explicit and enforced
- file intent helpers preserve canonical ordering and validation
- bootstrap state is normalized enough for predictable client reasoning
- version surfaces are distinct enough to avoid misleading interpretations
- ticket persistence is documented as convention rather than overstated as server protocol

## Non-goals

v0.5.0 does not attempt to provide:

- a full project-management system
- mandatory server-managed ticket artifact synchronization
- replacement of the canonical transaction/event model with a softer helper-only abstraction
- silent repair of invalid client workflows that violate ordering guarantees

## Final note

The key interoperability principle for v0.5.0 is simple:

The server should strictly enforce the canonical workflow it actually supports, and the public documentation should clearly mark the boundary between enforced protocol and client-side convention.

That boundary is what allows clients to integrate safely without depending on undocumented behavior or overstated guarantees.