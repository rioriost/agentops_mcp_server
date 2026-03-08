# Draft for 0.5.0: client/server workflow alignment review for AgentOps MCP

## Background

Version 0.4.13 completed a substantial hardening of the transaction-oriented MCP server implementation under `src/agentops_mcp_server`. The current system now exposes a richer set of tools and stronger event/state invariants around:

- workspace binding,
- transaction event logging,
- materialized transaction state,
- verification,
- commit sequencing,
- handoff generation,
- and task lifecycle operations.

At the same time, the client-side operating contract is defined by two additional artifacts:

- `zed-agentops-init.sh`
- `.rules`

These define how an MCP client is expected to initialize a workspace, restore or resume prior work, drive ticket-oriented execution, emit events, persist status, verify work, commit changes, and export resumable state.

Because the AgentOps model is not only a server implementation but also a client/server protocol discipline, correctness depends on all three layers remaining aligned:

1. the MCP server implementation in Python,
2. the bootstrap/init script that provisions client-visible rules and state files,
3. the rules document that prescribes the workflow.

This draft documents the current alignment state after 0.4.13, with particular focus on:

- MCP tool contracts,
- status transitions,
- work loop semantics,
- ticket lifecycle expectations,
- and client/server interoperability.

## Scope of review

This draft evaluates consistency between:

- the Python implementation under `src/agentops_mcp_server`,
- the generated scaffolding and rules text implied by `zed-agentops-init.sh`,
- the repository `.rules` document.

The main question is not whether each component works in isolation, but whether they define one coherent operating model from the perspective of:

- an MCP server exposing tools,
- and an MCP client that is expected to follow the rules strictly.

## Executive summary

The current state is best described as follows:

- the server-side transaction/event model is already fairly strong,
- the low-level invariants around verify/commit/file-intent sequencing are meaningfully enforced,
- but the higher-level ticket-oriented workflow described in `.rules` is not yet fully implemented or fully enforceable by the server.

In other words:

- **event-level alignment is relatively good**
- **ticket/workflow-level alignment is still incomplete**

The most important conclusion is:

> The MCP server already behaves like a strict transaction log engine, but `.rules` currently describes a stricter ticket lifecycle protocol than the server fully supports.

This means the server and client contract is partially aligned, but not yet fully closed.

## Current strengths

### 1. Workspace initialization is explicitly modeled

The current model exposes explicit workspace initialization semantics and protects file-backed operations from running before a project root is established.

This aligns well with the rules expectation that workspace initialization must happen before canonical restore or file-backed operations.

Key aligned behaviors include:

- `cwd` is required,
- root `/` is rejected,
- same-root reinitialization behaves as a no-op,
- rebinding to a different root is rejected,
- root-dependent operations are guarded.

This is one of the strongest areas of alignment.

### 2. Canonical transaction artifacts are clearly distinguished

The implementation and rules both distinguish:

- canonical artifacts:
  - `.agent/tx_event_log.jsonl`
  - `.agent/tx_state.json`
- derived artifacts:
  - `.agent/handoff.json`
  - observability summaries
- runtime/error artifacts:
  - `.agent/errors.jsonl`

This is an important correctness property because resumability decisions are intended to come from canonical state, not from derived summaries.

### 3. Transaction event taxonomy is substantially implemented

The server-side implementation already understands and validates a meaningful transaction event set, including:

- `tx.begin`
- `tx.step.enter`
- `tx.file_intent.add`
- `tx.file_intent.update`
- `tx.file_intent.complete`
- `tx.verify.start`
- `tx.verify.pass`
- `tx.verify.fail`
- `tx.commit.start`
- `tx.commit.done`
- `tx.commit.fail`
- `tx.end.done`
- `tx.end.blocked`
- `tx.user_intent.set`

This is consistent with the strict transaction model described in the rules.

### 4. Important ordering invariants are enforced

A strong part of the current implementation is that several critical sequencing rules are enforced rather than merely documented.

Examples include:

- `tx.begin` is required before other events,
- `tx.verify.start` must precede `tx.verify.pass` or `tx.verify.fail`,
- `tx.commit.start` requires a prior successful verify state,
- file intent updates require a registered file intent for the same path,
- file intents cannot regress in state,
- file intent verification requires prior verify pass,
- terminal transactions reject follow-up non-terminal events.

These invariants are central to the safety model and are already in relatively good shape.

### 5. Error logging and state rebuild concepts exist

The implementation includes mechanisms for:

- logging tool failures,
- rebuilding transaction state from event history,
- detecting certain forms of state drift,
- exporting compact or resumable context.

This is aligned with the broader goal of resumability and interruption safety.

## Major alignment gaps

## 1. `.rules` and `zed-agentops-init.sh` do not fully agree

### Problem

The repository-level `.rules` and the `.rules` text embedded into `zed-agentops-init.sh` are not fully identical.

The current repository `.rules` contains stronger start/resume requirements, including logic such as:

- if `active_tx.status` is non-terminal, resume it first,
- do not start a new ticket while a non-terminal transaction exists,
- only select the next executable ticket when there is no active transaction to resume.

The embedded rules text in the init script is missing at least part of that stricter wording.

### Why this matters

This means a newly initialized client workspace may receive a ruleset that is weaker or different from the repository’s current intended protocol.

That creates a direct client/server alignment problem:

- the server may assume one operational contract,
- the generated client rules may communicate a slightly different one.

### Required outcome

For 0.5.0, the bootstrap script and canonical `.rules` should be kept textually synchronized, or generated from one source of truth.

## 2. The rules prescribe a ticket protocol that the server does not fully implement

### Problem

The rules now describe a full planning and ticket persistence protocol, including:

- `docs/__version__/plan.md`
- `docs/__version__/tickets_list.json`
- `docs/__version__/pX-tY.json`
- synchronized status persistence between per-ticket documents and ticket list metadata

However, the current MCP server implementation does not provide a corresponding ticket persistence subsystem.

There is currently no complete server-side support for:

- generating ticket files,
- updating them throughout lifecycle transitions,
- enforcing synchronization between per-ticket JSON and `tickets_list.json`,
- validating those documents against runtime transitions.

### Why this matters

The rules describe this behavior as mandatory. From a client/server contract perspective, that creates a mismatch:

- the client is instructed to persist ticket documents,
- the server does not provide first-class primitives to support or enforce that model.

This is the single biggest alignment gap.

### Required outcome

For 0.5.0, one of the following must happen:

1. implement ticket persistence as a first-class server-supported workflow, or
2. downgrade these requirements in `.rules` from mandatory protocol to external operating convention.

Without that, the client is being required to do work the server does not structurally support.

## 3. Task lifecycle tools do not fully model the rules’ status machine

### Problem

The rules describe a strict top-level status progression:

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

The server does track those values at the transaction state layer, but the higher-level lifecycle tools do not map to them with complete precision.

In particular:

- task start/update/end operations are not a full status transition engine,
- intermediate lifecycle states are not all represented as distinct high-level operations,
- some lifecycle tool behavior translates user intent into generic step events rather than explicit status transitions.

### Why this matters

From the client perspective, `.rules` implies that ticket status progression is explicit and synchronized at every lifecycle step.

From the server perspective, some of these transitions are implicit consequences of:

- verify events,
- commit events,
- or generic step-enter events.

This means the client-visible lifecycle model is stricter and more explicit than the server’s actual operational surface.

### Specific concerns

#### A. Start semantics are looser than the rules imply

Task start accepts an optional status and can use it as a phase input. This is more permissive than the intended model, where task start should normally mean entering `in-progress`.

#### B. Update semantics are not a precise state transition API

Task update is closer to “record progress” than “apply one exact lifecycle transition.” It can emit step-oriented progress without functioning as a strict status state machine.

#### C. End semantics only cover terminal outcomes

Task end maps naturally to terminal states such as `done` or `blocked`, but it is not the abstraction that carries intermediate statuses such as `checking`, `verified`, or `committed`.

### Required outcome

For 0.5.0, lifecycle tooling should either:

- become a stricter status-aware API, or
- be clearly documented as thin event helpers rather than the canonical lifecycle interface.

## 4. Commit workflow enforcement is weaker than the rules describe

### Problem

The rules require:

- verify before commit,
- repo status inspection after verify,
- commit only if changes exist,
- concise commit messages.

The implementation already handles some of this:

- verify-before-commit exists in helper flows,
- commit message normalization exists,
- repo status summary tooling exists,
- verify/commit event ordering is guarded.

However, there is still a gap between “possible” and “required.”

Examples:

- the implementation does not universally enforce an explicit repo status check before every commit,
- change existence is not always treated as a dedicated precondition; instead, a zero-change commit may simply fail at the git layer,
- the rule “commit only if changes exist” is not fully elevated into protocol enforcement.

### Why this matters

The rules describe this as a strict work loop requirement. The server should ideally make this requirement hard to violate.

### Required outcome

For 0.5.0, the commit layer should explicitly gate on:

- verified state,
- existing changes,
- and, ideally, an observable repo status snapshot.

## 5. File intent semantics exist, but client ergonomics are still low-level

### Problem

The rules require file intent registration before mutation, and the transaction model already supports file intent events.

This is good at the invariant layer, but the public client experience is still fairly raw:

- the core primitive is transaction event emission,
- there is not yet a more ergonomic file-intent-specific tool layer.

### Why this matters

From a client/server perspective, the rules require behavior that is valid but operationally cumbersome:

- a client has to correctly construct low-level file intent events,
- preserve exact field names and ordering,
- and avoid protocol mistakes without much ergonomic help.

### Required outcome

For 0.5.0, the system should consider first-class file intent helper tools, for example:

- register file intent,
- mark file intent started,
- mark file intent applied,
- mark file intent verified.

That would preserve the event model while making the client contract far easier to follow safely.

## 6. Runtime initialization semantics are slightly looser than the rules wording

### Problem

The runtime does a good job of exposing and checking workspace initialization, but the internal startup path may already hold a root depending on process cwd.

This is not a public protocol break by itself, but it means the implementation is a little more permissive internally than the rules language suggests.

### Why this matters

The rules describe `workspace_initialize` as a mandatory first action before root-dependent operations. Internally pre-bound state weakens the conceptual cleanliness of that model.

### Required outcome

For 0.5.0, either:

- make explicit initialization the only canonical path, or
- document the runtime convenience behavior as implementation detail while keeping the public contract unchanged.

## Secondary alignment issues

## 1. Initial `tx_state.json` shape is compatible but not fully normalized

The init script creates a baseline transaction state file that is compatible with runtime expectations, but the shape is not fully identical to the richer state shape produced by rebuild/runtime logic.

Examples of shape drift include fields such as:

- `drift_detected`
- `active_tx_source`

This is not a critical failure because compatibility is maintained, but normalization would improve predictability.

## 2. Version surfaces are potentially confusing

There are multiple version concepts in play:

- implementation/package/server version,
- transaction schema version,
- release/draft version.

A server info version that does not obviously match the current release line can confuse clients or operators, even if schema versioning is intentionally separate.

For 0.5.0, version surfaces should be reviewed for clarity.

## 3. Time lookup rules mention a contract not implemented by this server

The rules mention constraints for time lookup input values. That is not inherently wrong, but if the server does not actually expose a corresponding tool, the rule may be more confusing than useful.

This is low priority, but cleanup would improve conceptual coherence.

## Alignment by topic

## MCP tool contract alignment

### Strong alignment

The following contracts are in relatively good shape:

- workspace initialization
- transaction event append
- transaction state save
- transaction state rebuild
- verify tooling
- commit tooling
- compact context / capture / handoff support

### Partial alignment

The following are present but need stronger semantics:

- task lifecycle tools
- commit policy enforcement
- client-side file intent ergonomics

### Missing alignment

The following are described by rules but not implemented as first-class server support:

- planning flow generation
- ticket document persistence
- synchronized ticket metadata updates
- acceptance-criteria / plan conformance checks

## Status transition alignment

### What is aligned

At the transaction core, the server recognizes and guards the intended top-level states:

- `planned`
- `in-progress`
- `checking`
- `verified`
- `committed`
- `done`
- `blocked`

It also tracks verification and commit sub-states.

### What is not yet fully aligned

What is still missing is a clean, client-facing transition interface that makes these statuses the explicit backbone of the high-level workflow.

At present:

- some statuses are represented directly,
- some emerge through event interpretation,
- some are implied by verify/commit helper behavior.

For a strict client/server workflow, this should become more explicit.

## Work loop alignment

### Good news

The low-level work loop ordering is increasingly solid:

- begin before further lifecycle work,
- verify start before verify result,
- verify pass before commit start,
- file intent verified after verify pass,
- commit result after commit start.

### Gap

The rules define a broader work loop than the server currently enforces. That broader loop includes:

- ticket-document persistence,
- synchronized status bookkeeping,
- plan/acceptance review,
- commit/no-commit decisioning tied to repo state.

This broader loop is not yet fully represented in the server implementation.

## Client/server interoperability assessment

From the point of view of an MCP client implementing the rules literally, the current situation is:

### What the client can do safely

A client can already:

- initialize a workspace,
- emit canonical transaction events,
- maintain transaction state,
- run verify,
- run commit,
- export resumable state,
- observe meaningful transaction invariants,
- avoid many classes of invalid sequencing.

### What the client cannot rely on the server to handle fully

A client cannot yet rely on the server to fully own:

- planning artifact generation,
- ticket metadata persistence,
- per-ticket and list synchronization,
- complete ticket lifecycle bookkeeping,
- acceptance/plan conformance checks as part of verify flow.

That means part of the workflow still lives as convention rather than as protocol.

## Recommended 0.5.0 direction

## Priority 0: eliminate contradictions between client rules and generated rules

The highest priority correction is to ensure that:

- repository `.rules`
- generated `.rules` in `zed-agentops-init.sh`

are textually identical or derived from one canonical source.

This is the minimum requirement for trustworthy client/server behavior.

## Priority 1: decide whether ticket persistence is protocol or convention

The project should make a clear decision:

### Option A: make it protocol

Implement first-class server support for:

- plan generation,
- ticket list generation,
- per-ticket metadata updates,
- synchronized status persistence.

### Option B: make it convention

If those functions are intentionally outside the MCP server boundary, then `.rules` should stop describing them as mandatory protocol requirements.

The current hybrid state is the worst of both worlds.

## Priority 2: make lifecycle APIs reflect the status machine more explicitly

For 0.5.0, task lifecycle APIs should move toward one of two models:

### Model 1: strict lifecycle interface

Introduce explicit status transitions as the main client contract.

### Model 2: low-level event interface

If the true canonical interface is event-oriented, document task helpers as convenience wrappers rather than authoritative lifecycle primitives.

The current ambiguity should be removed.

## Priority 3: tighten commit gating

Commit operations should explicitly enforce:

- verified state,
- change existence,
- and preferably repo-status awareness.

This would turn a documented rule into a server-enforced protocol property.

## Priority 4: improve file intent ergonomics

Introduce a first-class file intent helper layer so that clients do not have to manually assemble raw intent events for common operations.

This would improve correctness without weakening the event model.

## Priority 5: normalize state bootstrap shape

The bootstrap state file and runtime-rebuilt state should converge on one normalized shape wherever possible.

This is lower priority but improves consistency and predictability.

## Proposed acceptance criteria for 0.5.0

Version 0.5.0 should aim to satisfy the following:

1. The repository `.rules` and generated `.rules` are identical in workflow-critical sections.
2. Workspace initialization semantics are unambiguous and enforced consistently.
3. The server exposes a clear canonical lifecycle model for:
   - start
   - progress/update
   - verify
   - commit
   - terminal completion
4. Commit is explicitly blocked when:
   - verify has not passed
   - or there are no changes to commit
5. The client can satisfy all mandatory `.rules` requirements using server-supported primitives.
6. If ticket persistence remains mandatory in `.rules`, the server provides first-class support for it.
7. If ticket persistence does not become server-supported, the rules are revised so they no longer claim it as mandatory protocol behavior.
8. File intent workflow is supported at an ergonomic client level, not only via raw low-level event emission.
9. Version surfaces and bootstrap state shape are made internally coherent.

## Final conclusion

The 0.4.13 implementation meaningfully improved the transaction core and is already much closer to a reliable resumable workflow engine than earlier versions.

However, the current system still has a split personality:

- the server behaves like a transaction/event engine,
- while the rules describe a fuller ticket workflow platform.

That gap is now the main alignment problem.

Therefore, the purpose of 0.5.0 should not primarily be more low-level event hardening. Instead, it should be to complete the protocol boundary between:

- what the rules require from a client,
- and what the MCP server actually supports and enforces.

The central design task for 0.5.0 is:

> make the documented workflow and the implemented workflow the same thing.

Once that is achieved, AgentOps will have a much stronger claim to being both:

- a correct transaction-aware MCP server,
- and a coherent client/server operating model for resumable ticket-based work.