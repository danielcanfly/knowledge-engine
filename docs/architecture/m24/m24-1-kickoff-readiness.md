# M24 Kickoff Readiness

M24 is ready to start non-serving work after bootstrap PR #964 merged at
`01c5ff461882893a2e0924bb9ea634f3cd06e378`.

The GitHub milestone is M24 issue milestone #1:
`https://github.com/danielcanfly/knowledge-engine/milestone/1`.

## Gate Topology

The first gated lane is #965, `M24 semantic promotion decision gate`.

#966, `M24 production semantic/hybrid retrieval implementation blocked by
promotion decision`, must remain blocked until #965 is accepted and reconciled.
Production semantic retrieval, production hybrid retrieval, semantic answer
serving, semantic promotion, and any production retrieval change away from
lexical must not merge or dispatch before #965 completes.

## Parallel Lanes

The following M24 product lanes may start now because they carry no production
semantic serving authority:

- #974 Source PR #19 manual review;
- #967 Canonical Source adoption planning;
- #973 Sigma.js internal deployment;
- #971 Obsidian exporter;
- #968 Concept Wiki;
- #970 lexical search UX;
- #972 provenance and source viewer;
- #969 Graph navigation.

These lanes may produce planning, review, internal tooling, UX, and graph/source
navigation work while production retrieval remains lexical.

## Authority Boundary

M24 kickoff readiness does not authorize production mutation, Qdrant mutation,
R2 mutation, Source mutation, pointer mutation, credential rotation, semantic
answer serving, semantic promotion, or production semantic/hybrid retrieval.

The kickoff-ready roadmap remains machine-readable at
`pilot/m24/m24-bootstrap-roadmap.json`, with `roadmap_sha256` binding the exact
issue topology and authority boundary.
