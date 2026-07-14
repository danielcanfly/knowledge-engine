# M23.4 Human Review and Draft Source PR

Status: implementation for issue #374

Production mutation dispatched: false.

## Exact entry baseline

- Engine: `5de0327501a8584098e5304160462c9c7e92daba`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.3 extraction packet: `32f29be6fa4a90d6495b0844fbe0e8a2003dec25d3adf5328a0fd0b2232ce402`
- M23.3 governed packet: `bc4a3c366d84baebd93982a39831fa7766e43a38018b0e0680e5b1c9f33c4875`

## Governance result

M23.4 routes the M23.3 candidate and governed packets through the existing M21.5 entity-resolution contract. The exact Source index contains the five reviewed Source concepts at the pinned Source SHA.

The current M21.5 contract treats shared governed tags as weak duplicate evidence. Every one of the fifteen Harness endpoints shares at least one governed tag with the five-concept Source, so each endpoint requires a human distinctness decision. This conservative result blocks automatic M21.6 packaging. It does not assert that the concepts are identical.

The M23.4 wrapper keeps all 38 extraction candidates accounted for by grouping claims, definitions, aliases and bilingual terms under their endpoint review items and preserving all 12 typed relations and 34 governed tags. It produces a decision template with only `pending` decisions.

## Source PR boundary

A dedicated draft Source PR is the human review surface. Proposed files live under `proposals/m23-4/` and carry `canonical-write-permitted: false`. They are not compiled by the Source bundle and must not be treated as canonical knowledge.

A human reviewer must choose one of:

- `approve_new`;
- `map_existing`;
- `edit`;
- `reject`;
- `defer`.

Only a later, explicit adoption step may convert approved proposals into canonical `bundle/concepts`, `provenance`, index and registry changes. M23.4 never claims that ChatGPT performed human approval and never merges the Source PR.

## Protected boundaries

No Source main mutation, human approval, canonical adoption, candidate or production publication, production pointer, R2 retention, embedding generation, traffic change, multi-hop activation, Graph Explorer deployment or Graph Neural Retrieval.
