# M19.4 Deterministic Graph Explorer Interactions

Status: implementation for issue #276
Production mutation dispatched: false

## Exact base

M19.4 starts only after M19.3 reconciliation, from Engine main
`9327bef8b1ad14cfbe9b7047ad97c8b26322a35b`. Source remains
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Local and ACL-safe boundary

All M19.4 controls operate only on the already ACL-filtered, read-only,
renderer-neutral Graphology graph accepted by M19.3. The package performs no
fetch, authentication, authorization broadening, persistence, or write-back.
The exact graph release identity remains visible in explorer state.

Search covers stable concept ID, title, aliases, bounded description, tags, and
concept type. Queries are NFKC-normalized, case-folded, capped at 160 characters,
and return at most 100 deterministically ranked results from the currently
visible ACL-safe view.

## Focus and filters

Focus traverses graph adjacency without changing canonical edge direction and
is bounded to exactly one or two hops. Relation filters are applied before
neighborhood traversal. Tag and type filters use OR semantics within each
filter family and AND semantics across families. Filter lists are normalized,
deduplicated, sorted, and capped at 50 values.

Orphan visibility is explicit. When disabled, zero-degree nodes are removed from
the current filtered view, except that an isolated focus node remains visible so
the UI cannot collapse into an unexplained blank state.

## Renderer-only state

Visibility and search match state are implemented through Sigma node and edge
reducers. Hidden, highlighted, size, label, and z-index values remain ephemeral
renderer output. The canonical graph is never mutated. A selected node is
cleared if a later filter or focus change removes it from the visible view.
Keyboard navigation and textual fallback follow the deterministic visible-node
ordering.

## Bounds and failure behavior

The implementation rejects overlong queries, oversized or invalid filter lists,
invalid neighborhood depths, focus nodes outside the ACL-safe graph, and
selection outside the visible ACL-safe view. Search, filtering, focus, and
teardown remain deterministic and CSP-compatible with no CDN or runtime network
client.

## Exclusions

M19.4 does not add provenance or detail panels, Markdown links, shareable URL
state, large-graph layout, communities, global overview, progressive loading,
production or Source preview, editing, publication, or Graph Neural Retrieval.
Issue #276 remains open until a separate reconciliation PR passes exact-head CI
and merges with its expected head.
