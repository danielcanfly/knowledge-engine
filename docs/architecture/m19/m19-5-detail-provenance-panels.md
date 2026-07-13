# M19.5 Release-bound Detail and Provenance Panels

Status: implementation for issue #279  
Production mutation dispatched: false

## Exact base

M19.5 starts only after M19.4 reconciliation, from Engine main
`b8f42052adfbc12b82c09ce49003b1915a663104`. Source remains
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Composition boundary

M19.5 is an additive `@knowledge-os/graph-explorer/details` submodule. It composes
with the visible node and edge sets produced by M19.4 without changing the
validated M19.4 search, focus, neighborhood, filter, keyboard, or textual fallback
implementation.

The controller accepts only the already ACL-filtered, read-only,
renderer-neutral Graphology graph. It performs no fetch, authentication,
authorization broadening, persistence, or write-back. Node and edge selection,
panel state, and reducer output are ephemeral.

## Exact release identity

The panel exposes the release identity already present on the M19.2 Graphology
graph:

- release ID;
- manifest SHA-256 when present;
- Source commit SHA when present;
- Foundation commit SHA when present;
- content SHA-256 when present.

An optional details bundle must declare the same complete identity. Missing,
additional, or different identity values fail closed, preventing metadata from
one release being displayed against another.

## Node and edge details

Node panels contain bounded canonical node fields, a validated relative Markdown
path, and approved provenance references. Edge panels contain the stable edge ID,
source and target summaries, relation type, direction, audience, confidence,
generated-inverse marker, and approved provenance references.

The details controller validates every node and edge record against the current
ACL-safe graph. Unknown records, duplicates, unsafe paths, absolute paths, URL
schemes, traversal segments, fragments, query strings, invalid anchors,
unapproved references, and more than twenty provenance references fail closed.
Raw evidence text and reviewer identity are intentionally absent.

## M19.4 integration

`reconcileVisible` accepts the deterministic visible node and edge IDs produced
by M19.4. If filtering or focus removes the selected object, panel state clears.
Node and edge reducers provide selection styling without mutating canonical or
projected graph attributes.

## Supply chain and validation

No runtime dependency is added. The existing exact Graphology, Sigma.js,
TypeScript, and Node versions remain pinned by the committed lockfile. The M19.5
workflow checks out the exact PR head, runs the M19.2 adapter regression suite,
the complete M19.3/M19.4 explorer suite plus M19.5 tests, and production-runtime
npm audits.

## Exclusions

M19.5 does not add shareable URL state, layout, communities, global overview,
semantic zoom, progressive loading, Source editing, candidate or production
publication, production pointer changes, R2 mutation, credentials, permanent
ledgers, rollback changes, M19.6 work, or Graph Neural Retrieval. Issue #279
remains open until a separate reconciliation PR passes exact-head CI and merges
with its expected head.
