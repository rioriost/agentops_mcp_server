# Phase 1-3 Traceability Framework for 0.6.0

## Canonical source rule
- `docs/v0.6.0/plan.md` is the only canonical source of requirements for `0.6.0`.
- All phase 1-3 ticket artifacts are derived from `plan.md`.
- No phase 1-3 ticket artifact may add canonical requirements that are absent from `plan.md`.
- Phase 0 artifacts remain reusable evidence and implementation analysis inputs, but they are not canonical requirements.

## Artifact authority model
- Canonical requirements: `docs/v0.6.0/plan.md`
- Ticket status authority: `docs/v0.6.0/tickets_list.json`
- Ticket execution detail: `docs/v0.6.0/p1-t*.json`, `p2-t*.json`, `p3-t*.json`
- Evidence / analysis artifacts: `docs/v0.6.0/phase0-implementation-map.md` and later verification artifacts

## Traceability rules
1. Every phase 1-3 ticket must list `canonical_source`, `source_plan_phase`, `source_plan_sections`, and `covered_requirements`.
2. Every covered requirement must be allocated from explicit `plan.md` sections.
3. Tickets may refine execution detail, but must not introduce new canonical semantics.
4. Status is tracked only in `tickets_list.json`.
5. Evidence artifacts may contain observations, gaps, and recommendations, but must label them as derived rather than canonical.

## Requirement allocation summary

### Phase 1
- `p1-t01`
  - `REQ-P1-SEMANTICS`
  - `REQ-P1-IDENTITY`
- `p1-t02`
  - `REQ-P1-STATE-MACHINE`
  - `REQ-P1-CHECKPOINTS`
- `p1-t03`
  - `REQ-P1-IDENTITY`
  - `REQ-P1-CHECKPOINTS`
  - `REQ-P1-PERSISTENCE`

### Phase 2
- `p2-t01`
  - `REQ-P2-ISSUED-TXID`
- `p2-t02`
  - `REQ-P2-NO-SENTINEL`
- `p2-t03`
  - `REQ-P2-EXACT-RESUME`
- `p2-t04`
  - `REQ-P2-SESSION-COMPAT`

### Phase 3
- `p3-t01`
  - `REQ-P3-INTERRUPTION`
- `p3-t02`
  - `REQ-P3-IDEMPOTENT`
- `p3-t03`
  - `REQ-P3-GUIDANCE`

## How to use phase 0 artifacts
- Use `docs/v0.6.0/phase0-implementation-map.md` as evidence and codebase orientation.
- Do not treat phase 0 observations as canonical requirements unless they are explicitly backed by `plan.md`.
- When a phase 1-3 ticket references phase 0, phase 0 is an input for implementation targeting, not a replacement for the plan.

## Completion rule
A phase 1-3 ticket may be marked `done` only when:
1. all of its covered requirements are implemented or evidenced,
2. the implementation/evidence is traceable back to `plan.md`,
3. no canonical behavior in the result contradicts `plan.md`,
4. no extra canonical requirement has been introduced outside `plan.md`.

## Phase 0 normalization
- Phase 0 ticket artifacts are now also normalized with `canonical_source`, `source_plan_sections`, and `covered_requirements`.
- Their role remains evidence and analysis, not canonical requirement definition.
- They may be cited as implementation inputs only when their observations remain consistent with `plan.md`.

## Phase 0 status meaning
- `done` for phase 0 means the evidence and analysis artifacts are complete enough for downstream plan-derived work.
- It does not mean that the plan-defined runtime implementation is complete.
