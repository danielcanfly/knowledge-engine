# M19.3 Sigma.js v3 Read-only Explorer Shell

Status: implementation for issue #273
Production mutation dispatched: false

## Exact base

M19.3 starts only after M19.2 reconciliation, from Engine main
`5b9d64a9eeb1c1926ac919ccd5125cdc56933d2d`. Source remains
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Package and supply chain

The shell is isolated in `packages/graph-explorer`. It pins Sigma.js `3.0.3`
stable and Graphology `0.26.0`, both MIT-licensed, plus exact TypeScript tooling
with a committed npm lockfile. There is no CDN import or runtime network client.
Sigma is loaded lazily only by the explicit browser entry point so the contract,
projection, and accessibility tests remain deterministic without WebGL.

## Renderer boundary

The shell accepts only a Graphology graph already marked `readOnly` and
`rendererNeutral` with a non-empty release identity. This is the graph produced
from M19.1 ACL-safe payloads by the M19.2 adapter; M19.3 performs no fetch and
has no authentication or ACL-broadening authority.

Renderer coordinates, labels, neutral colors, sizes, and edge display values are
added only to an ephemeral Graphology copy. The canonical input graph is never
mutated. Selection styling uses a Sigma node reducer and cannot become canonical
truth or write back to Source, Runtime, a release, or the API.

## Shell behavior

The browser entry point constructs Sigma.js v3 with CSP-compatible local module
loading. The shell supports click selection, stage deselection, deterministic
arrow/Home/End/Escape keyboard selection, camera reset, idempotent teardown,
bounded selected-node text, and a deterministic textual fallback capped at 500
nodes. It exposes exact release identity and read-only state.

The container receives focus, application role, and an accessible label while
mounted; its prior attributes are restored on teardown. Color is not used as
the only selection signal: the reducer also changes size, highlight, z-index,
and forced label state.

## Exclusions

M19.3 does not add search, focus or neighborhood expansion, relation/tag/type
filters, orphan controls, provenance panels, Markdown links, shareable view
state, layouts, communities, global overview, performance tiers, progressive
loading, production or Source preview, editing, publication, or Graph Neural
Retrieval. Issue #273 remains open until a separate reconciliation PR passes
exact-head CI and merges with its expected head.
