# M19.6 Release-Bound Large Graph Strategy

Status: implementation for issue #282  
Production mutation dispatched: false

## Exact base

M19.6 starts only after M19.5 reconciliation, from Engine main
`9c0f75237e9dc7db4e7cf2c805f477a674460a75`. Source remains
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Derived layout contract

The additive `@knowledge-os/graph-explorer/scale` module creates a read-only
`knowledge-os-graph-layout/v1` artifact from an already ACL-filtered,
renderer-neutral Graphology graph. Layout identity includes the exact release,
manifest, Source, Foundation, and content identities available on that graph.

Coordinates are deterministic for a fixed graph, pinned algorithm
`knowledge-os-deterministic-hash-ring` version `1.0.0`, and unsigned 32-bit seed.
They are release-bound materialized-view data only. Canonical graph validity,
retrieval, provenance, and Source never depend on coordinates.

Layout validation rejects cross-release identity, unsupported algorithm identity,
count mismatch, missing or duplicate node positions, nodes outside the ACL-safe
graph, non-finite coordinates, mutable or renderer-specific graphs, more than
50,000 nodes, or more than 250,000 edges.

## Global overview and semantic zoom

`knowledge-os-graph-overview/v1` groups nodes deterministically by normalized
primary tag, falling back to concept type. The largest groups remain explicit and
bounded overflow becomes `Other`. Representatives are selected by degree and
stable ID; coordinates are release-bound centroids of the validated layout.

Inter-cluster edges aggregate stable direction, weight, and at most twenty
relation types. The overview contains no description bodies, raw evidence,
provenance, reviewer identity, or unrestricted metadata. Cluster and edge counts
are capped at 500 and 2,000.

Semantic zoom returns deterministic overview, context, or detail policies with
explicit label and edge budgets. Low zoom and very large node counts use the
overview artifact; labels and edges expand only within bounded policies. The
policy is data-only and does not mutate Sigma or canonical graph attributes.

## Progressive local exploration

One- and two-hop neighborhoods can be emitted as deterministic cursor pages with
at most 500 nodes and 1,000 edges per page. Relation filters are normalized,
deduplicated, sorted, and bounded. Cursors record only node and edge offsets
inside the already authorized bounded neighborhood.

Unknown roots, invalid depths, oversized batches, invalid cursors, cursor drift,
and objects outside the ACL-safe graph fail closed. The planner performs no
network request, persistence, authentication change, or write-back. A caller may
use its pages to stage an intentional local view without downloading bodies or
evidence.

## Performance tiers and evidence

Budgets are defined before acceptance for 1,000, 10,000, and 50,000 nodes. They
cover edge count, payload bytes, parse/import, deterministic layout, overview,
first meaningful render input preparation, pan/zoom and selection proxies,
neighborhood planning, memory, label suppression, and edge reduction.

The exact-head workflow runs five synthetic fixtures:

- 1,000 nodes, sparse edges;
- 1,000 nodes, dense edges;
- 10,000 nodes, sparse edges;
- 10,000 nodes, medium edges;
- 50,000 nodes, sparse edges.

Fixtures serialize and parse renderer-neutral payloads, import Graphology,
materialize layout and overview artifacts, exercise semantic zoom and progressive
neighborhood planning, emit JSON metrics, and fail when any tier exceeds its
budget. Browser-specific paint telemetry remains an M19.7 acceptance concern;
M19.6 supplies its explicit budget fields without uploading telemetry.

## Safety and exclusions

The module adds no dependency, CDN, runtime network client, browser storage,
mutation verb, canonical attribute write, server endpoint, production or
candidate publication, production pointer, R2 object, credential, permanent
ledger, rollback action, cross-release merge, M19.7 closure, or Graph Neural
Retrieval. Issue #282 remains open until a separate reconciliation PR passes its
own exact-head CI and merges with its expected head.
