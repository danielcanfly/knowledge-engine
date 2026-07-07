# M8-001 Source Scope Proposal

Status: `planned`

Parent: `#87`

Tracker: `#88`

## Origin

- Repository: `huaihsuanbusiness/daniel-blog`
- Commit: `27e2fe996f878f2129bf510d6a326c02f7d87be5`
- Path: `src/content/blog/the-atlas-of-agent-design-patterns-part-2/en.md`
- Blob SHA: `9b8912a4dc0193c0c478bcfe83dfaccff21b7ffe`
- Public citation: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-2/`

## Intended canonical Source path

`bundle/concepts/agent-execution-paths.md`

## Included knowledge

The proposed concept should capture universal engineering knowledge about:

- the difference between outer execution structure and node-level decision logic
- Direct, Pipeline, Router, State Machine, and DAG as distinct but composable structures
- when each structure is a strong baseline
- router abstention, overrides, confidence, permissions, and observability
- explicit states, legal transitions, guards, terminal outcomes, persistence, and recovery
- DAG dependency, bounded concurrency, join rules, and provenance preservation
- event-driven triggers and delivery realities such as replay and idempotency
- human approval as a governed pause and resume point
- behavior trees as a related hierarchical control structure
- program generation as an execution technique rather than a separate topology
- a practical structure-selection sequence
- production controls shared across all structures

## Excluded knowledge

The canonical concept should not copy:

- article navigation or series promotion
- image captions and image paths
- framework marketing language
- vendor-specific implementation instructions
- long examples that do not add a reusable engineering rule
- claims that cannot retain a source citation
- M6 Part 1 material about the complete six-dimensional architecture map

## Boundary with M6

M6 Part 1 defines six architecture dimensions. M8-001 expands only the execution-path dimension. It does not redefine the full map or Source governance.

## Review questions

1. Are the five primary structures described without treating them as a maturity ladder?
2. Are event-driven execution and human approval described as cross-cutting layers?
3. Are state-machine and DAG semantics kept distinct?
4. Are retry, idempotency, concurrency, terminal outcomes, and auditability preserved?
5. Can every public claim retain the Part 2 citation?

## Current decision

This proposal may proceed to `open_source_review` after registry, origin, non-overlap, preflight, and readiness evidence pass.

No canonical Source file has been created by this proposal.
