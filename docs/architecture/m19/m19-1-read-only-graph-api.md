# M19.1 Read-only Graph API and ACL Contract

Status: implementation for issue #267  
Production mutation dispatched: false

## Exact base

M19.1 starts from fully reconciled M18 Engine main
`f2957a9ce5c38f2af6f13b27c3ed55e0b67b431c`. The accepted Source identity is
`a6ba738d910d01d2ae99b1968f0831989934c549`, and Foundation remains
`e5ef644053d34e89c70d2ceb37521e1c59234832`.

## Surface

The Graph API exposes only these authenticated read operations:

- `GET /v1/graph/capabilities`;
- `GET /v1/graph/release`;
- `GET /v1/graph/search`;
- `GET /v1/graph/node/{concept_id}`;
- `GET /v1/graph/neighborhood/{concept_id}`;
- `GET /v1/graph/overview`.

The OpenAPI contract is scanned to ensure no POST, PUT, PATCH, or DELETE graph
operation exists. M19.1 does not provide the optional internal export endpoint.

## ACL and data boundary

The service reads only the already verified active Runtime release. It rejects
unknown audience meanings, duplicate nodes or edges, missing endpoints, release
identity mismatch, non-v2 schemas, and renderer fields. Nodes are filtered by
the principal's authorized audiences before serialization. Edges are retained
only when the edge and both endpoints are authorized.

Unauthorized and nonexistent node lookups both return the same 404 contract.
This prevents existence disclosure. Public graph payloads omit provenance paths,
claim/review identities, qualifiers, and raw evidence. Descriptions, tags,
aliases, paths, nodes, edges, response bytes, and execution time are bounded.

## Bounds

| Control | Limit |
|---|---:|
| neighborhood depth | exactly 1 |
| search results | 50 |
| neighborhood nodes / edges | 100 / 200 |
| overview nodes / edges | 400 / 800 |
| response bytes | 512,000 |
| service execution | 1 second |

The only M19.1 overview mode is renderer-neutral `none`. Communities, layouts,
coordinates, browser models, Graphology, Sigma, and tens-of-thousands
performance tiers remain later M19 work.

## Compatibility and safety

Capabilities and release identity remain available for an older verified
release without graph v2, but graph-data endpoints return an explicit capability
conflict. M19.1 does not modify Runtime refresh, retrieval ranking, relation
feature flags, Source, Foundation, releases, candidate or production state,
production pointers, R2, credentials, permanent ledger, or rollback state.
Graph Neural Retrieval remains excluded.

Issue #267 stays open until the implementation merges with its expected head and
a separate reconciliation PR records exact CI and merged identities.
