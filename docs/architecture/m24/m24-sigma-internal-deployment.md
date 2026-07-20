# M24 Sigma.js Internal Deployment

This advances #973 while production retrieval remains lexical.

The deployment target is internal review only. It reuses the existing
`packages/graph-explorer` Sigma.js v3 shell and the server-side ACL-filtered
read-only graph API. The committed deployment manifest is digest-bound and
records the package identity, graph data contract, access boundary, visual QA,
performance checks, and forbidden authority.

## Internal Target

- surface: internal review;
- audience: internal;
- public indexing: disabled;
- public share URL: disabled;
- production serving: disabled.

## Graph Data Contract

The internal view consumes `knowledge-engine-graph-api/v1` payloads from:

- `/v1/graph/capabilities`;
- `/v1/graph/release`;
- `/v1/graph/search`;
- `/v1/graph/node/{concept_id}`;
- `/v1/graph/neighborhood/{concept_id}`;
- `/v1/graph/overview`.

Inputs remain renderer-neutral and server-side ACL filtered. The browser does
not gain ACL-broadening, write-back, Source mutation, pointer mutation, Qdrant
mutation, R2 mutation, credential rotation, or production release authority.

## Visual QA and Performance

The required local checks are:

- `npm --prefix packages/graph-explorer test`;
- `npm --prefix packages/graph-explorer run performance:fixtures`;
- `npm --prefix packages/graph-explorer run acceptance:scan`.

Visual QA must cover nonblank canvas or textual fallback, keyboard selection,
camera reset, color-independent relation text, bounded selected-node text, and
container teardown.

## Boundary

- production retrieval remains `lexical`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- runtime CDN imports are disallowed;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.
