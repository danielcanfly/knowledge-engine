# M15.5 Freshness Impact Graph and Propagation

Parent: #204  
Slice: #213

## Baseline

- Engine: `34f8f14f6fa9d756a1767b1daecef9bb4757ad55`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Model

The graph contains closed node kinds for Source facts, concepts, pages, indexes, releases, caches, and public surfaces. Closed edge kinds represent derivation, reference, materialization, publication, and caching dependencies.

The graph is bounded, node identifiers are unique, and every edge endpoint must exist. Nodes carry only bounded identity and audience metadata; raw text, excerpts, URLs, and private object locations are not contract fields.

## Propagation

Changed nodes are marked direct. Allowed downstream dependencies become transitive impacts using deterministic breadth-first traversal. Traversal order and output ordering are stable. Maximum depth is explicit and bounded; truncation is represented as unknown rather than silently discarded.

Audience may never broaden during propagation. A dependency from private to internal or public, or internal to public, is emitted as blocked and propagation stops at that boundary.

Cycles, Engine identity drift, unknown changed nodes, orphan edges, duplicate node IDs, and depth truncation fail closed or are represented explicitly.

## Evidence

Reports use canonical sorted JSON and SHA-256 identity. Equal graphs, changed-node sets, and depth limits produce identical artifacts. Modified reports fail digest verification.

## Governance boundary

M15.5 is advisory only. It cannot edit Source, create correction candidates, dispatch work, rebuild releases, mutate production pointers, purge caches, write or delete R2 objects, promote, roll back, delete data, or append permanent ledger #30.
