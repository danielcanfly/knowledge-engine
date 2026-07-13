# M19.2 Graphology Adapter and Renderer Boundary

Status: implementation for issue #270
Production mutation dispatched: false

## Exact base

M19.2 starts only after M19.1 reconciliation, from Engine main
`61a97f3fdca3b16b44cb9e6d8b5921228291c37c`. Source remains
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Package and pinned supply chain

The adapter is isolated in `packages/graphology-adapter`. It pins Graphology
`0.26.0` (MIT), TypeScript `7.0.2` (Apache-2.0), and `@types/node` `26.1.1`
(MIT) with exact versions and a committed npm lockfile. Its only runtime
dependency is Graphology. It contains no Sigma package or import.

## Adapter contract

Two explicit entry points create a Graphology graph:

- `knowledgeGraphV2ToGraphology` validates a canonical
  `knowledge-os-graph/v2` artifact;
- `graphApiPayloadToGraphology` validates an ACL-safe, read-only
  `knowledge-engine-graph-api/v1` neighborhood or overview payload.

Both paths pin optional expected release identity. API input may additionally
pin the expected manifest SHA. Canonical input cannot claim a manifest identity
it does not contain.

The adapter always creates a mixed, multi-edge Graphology graph with self-loops
disabled. It preserves concept and edge keys, directed and undirected semantics,
relation types, audiences, confidence, generated-inverse markers, release
identity, and canonical descriptive attributes. Sorting nodes and edges before
insertion makes Graphology export deterministic across input order.

## Fail-closed boundary

The adapter rejects unsupported schemas, non-read-only API payloads, release or
manifest mismatch, unknown ACL values, renderer fields, malformed attributes,
non-boolean direction, duplicate stable IDs, missing endpoints, and self-loops.
It copies arrays rather than mutating its input.

Provenance object paths, raw evidence, review identity, qualifiers, renderer
fields, coordinates, colors, layouts, reducers, camera state, and Sigma options
are not copied into Graphology attributes. The resulting graph is an ephemeral
browser model and has no write-back path to Source, Runtime, releases, or the
Graph API.

## Exclusions

M19.2 does not add a Sigma renderer, React components, Explorer UX, layouts,
communities, global or local view modes, performance fixtures, production or
Source preview, editing, candidate publication, production activation,
embeddings, multi-hop reasoning, or Graph Neural Retrieval. Issue #270 remains
open until implementation and separate reconciliation PRs pass exact-head CI
and merge with their expected heads.
