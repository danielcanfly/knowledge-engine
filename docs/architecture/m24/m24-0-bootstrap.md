# M24 Bootstrap Roadmap

M24 starts after M23.7 R3.8 closure. The accepted source closure is PR #963 and
live confirmation run `29715599032`, with semantic live acceptance complete and
both M23.7 R3 blockers cleared.

M24 does not start by silently promoting semantic retrieval. Production retrieval
remains `lexical`, semantic answer serving remains disabled, hybrid retrieval
remains disabled, and protected mutations remain unauthorized until a separate
explicit promotion decision lands.

## First gated lane

The first gated M24 lane is `semantic_promotion_decision`.

This lane may start now as a decision and design workstream. It must define:

- authority boundary;
- rollout plan;
- rollback plan;
- serving contract;
- production metrics;
- failure triggers;
- operator or PR authorization.

It must complete before any production retrieval change, production hybrid
retrieval, semantic answer serving, or semantic promotion.

The bootstrap itself authorizes none of those actions.

## Parallel product lanes

The following lanes may start in parallel and are not blocked by semantic
promotion, as long as they do not grant production semantic serving authority:

- Source PR #19 manual review;
- Canonical Source adoption planning;
- Sigma.js internal deployment;
- Obsidian exporter;
- Concept Wiki;
- lexical search UX;
- provenance and source viewer;
- Graph navigation.

These lanes can improve the product surface, internal review flow, source
visibility, and graph navigation while production retrieval remains lexical.

## Authority boundary

This bootstrap grants no promotion, answer serving, production mutation, Qdrant
mutation, R2 mutation, Source mutation, pointer mutation, credential rotation, or
production retrieval change.

The machine-readable roadmap is `pilot/m24/m24-bootstrap-roadmap.json`. Its
deterministic digest is recorded as `roadmap_sha256`.

After PR #964 merged, M24 kickoff readiness is tracked in
`docs/architecture/m24/m24-1-kickoff-readiness.md`.
