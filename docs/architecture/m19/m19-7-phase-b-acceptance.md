# M19.7 Phase B Graph Visibility Acceptance

Status: implementation acceptance for issue #285

## Exact baseline

- Engine base: `6d85ca55a7d6b4b16bd3d304d17617f809dc76a0`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M19.1 issue / implementation / reconciliation: #267 / #268 / #269
- M19.2 issue / implementation / reconciliation: #270 / #271 / #272
- M19.3 issue / implementation / reconciliation: #273 / #274 / #275
- M19.4 issue / implementation / reconciliation: #276 / #277 / #278
- M19.5 issue / implementation / reconciliation: #279 / #280 / #281
- M19.6 issue / implementation / reconciliation: #282 / #283 / #284

All six predecessor submilestones are closed before M19.7 begins. M19.7 does not reopen or rewrite their accepted implementation contracts.

## Acceptance surface

M19.7 adds an isolated `@knowledge-os/graph-explorer/acceptance` contract. It does not create a second graph model and does not add renderer, network, storage, publication, or mutation authority.

The acceptance contract provides:

1. explicit production, candidate-preview, and Source-preview release descriptors;
2. exact release, manifest, Source, Foundation, and content identity carriage;
3. rejection of any composition that attempts to mix different release identities;
4. text, relation type, direction, endpoint labels, and directional symbols so relation meaning never depends on color alone;
5. one fail-closed authority manifest for server-side ACL, GET-only API authority, renderer-neutral input, CSP-compatible packaging, keyboard navigation, textual fallback, and bounded requests;
6. explicit empty authority sets for mutation routes, browser network clients, browser persistence, and write-back targets.

Preview views are always labelled non-production and include a warning. A preview cannot be silently represented as the active Runtime release.

## Static authority scan

`packages/graph-explorer/acceptance/phase-b.ts` scans Graphology adapter and explorer TypeScript sources. Acceptance fails when it finds browser/runtime network clients, browser persistence, cookies, dynamic code evaluation, or an unexpected explorer runtime dependency.

The allowed explorer runtime dependency set remains exactly:

- `graphology`;
- `sigma`.

The scan is deterministic, local, read-only, and emits a machine-readable report. It uploads no telemetry and changes no repository or runtime state.

## Exact-head acceptance workflow

The M19.7 workflow checks out the pull-request head SHA explicitly and verifies the checked-out commit before any test runs.

It then runs:

- M19.1 Graph API lint and ACL/bounds/release/read-only tests;
- a mutation-decorator scan over the Graph API module;
- the complete Graphology adapter suite;
- the complete Graph Explorer suite, including accessibility and authority tests;
- all 1k, 10k, and 50k sparse/medium/dense performance fixtures;
- the CSP, network, persistence, and write-back source scan;
- production-runtime npm audits at high severity;
- Python and TypeScript compilation.

Repository CI independently retains full quality gates, the reference vertical slice, and the container build.

## Security and accessibility closure

Phase B acceptance requires all of the following simultaneously:

- ACL filtering occurs before browser serialization;
- unauthorized and missing graph objects do not create an information oracle;
- Graph API authority is GET-only;
- query, depth, node, edge, payload, and execution surfaces are bounded;
- canonical graph input remains renderer-neutral and read-only;
- browser graph packages contain no runtime fetch, WebSocket, EventSource, beacon, cookie, local/session storage, IndexedDB, eval, or Function-constructor authority;
- packaging requires no runtime CDN or inline script;
- keyboard selection, stage clearing, camera reset, and textual fallback remain accepted;
- relations expose readable type and direction in addition to visual styling;
- production and non-production views are explicitly labelled and never cross-release merged.

## Closure boundary

M19.7 closes Graph Visibility only after a separate reconciliation PR records the final expected-head evidence.

This implementation does not modify or promote production, candidate publication, the production pointer, R2 objects, credentials, permanent ledgers, or rollback state. It adds no M20 hybrid retrieval implementation and no Graph Neural Retrieval.
