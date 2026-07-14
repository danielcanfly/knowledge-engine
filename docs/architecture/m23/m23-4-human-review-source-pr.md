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

## Closure reconciliation

M23.4 implementation and the review surface were reconciled against live GitHub evidence.

- authoritative Engine issue: #374;
- Engine implementation PR: #375;
- exact implementation base: `5de0327501a8584098e5304160462c9c7e92daba`;
- accepted implementation head: `7e6d754cd2df9bad689d33cf88530d19ee067068`;
- expected-head implementation merge: `4cdc9196f7556e0dd42f38955b7c0286b93bcc2c`;
- Source draft review PR: `knowledge-source#19`;
- Source review head: `deb3ad1e631c2149183d10561fbceb0a1848a989`;
- Source PR state at reconciliation: open, draft, unmerged;
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`.

The implementation diff contains exactly seven files. The accepted head passed M23.4 Human Review Source PR #1, CI #759, M23.3 #4, M23.2 #5, M17 Architecture #113, M18 Graph v2 #195, R2 Release Integration #508, R2 Canary #236, and every triggered M16/M17 safeguard. PR #375 had no conversation comments, submitted reviews, or unresolved review threads.

The Source draft PR contains exactly five files under `proposals/m23-4/`: review overview, pending decision template, compact concept proposals, candidate-ID review manifest, and evidence-offset provenance summary. It changes no canonical Source path.

The tooling milestone is complete, while all fifteen human decisions and canonical adoption remain explicitly pending. M23.5 and M23.6 must not treat these proposals as accepted Source knowledge.
