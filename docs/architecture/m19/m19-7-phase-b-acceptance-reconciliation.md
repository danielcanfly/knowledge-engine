# M19.7 Phase B Graph Visibility Reconciliation

Status: ready to close issue #285 and Phase B / M19

## Identity chain

- M19.6 reconciled Engine base: `6d85ca55a7d6b4b16bd3d304d17617f809dc76a0`
- M19.7 issue: #285
- implementation PR: #288
- implementation expected head: `9ca1385a7a7afbe84fd4f2fe8d31be0b400681b4`
- implementation merge: `bfd45d8164e2385d87283be73697c41bfd8846a0`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

The reconciliation branch was created from the exact implementation merge SHA. This PR closes #285 only after its own expected-head checks pass.

Issues #286 and #287 were accidental empty tool-routing artifacts. Both were immediately closed as `not planned`, explicitly point back to #285, and carry no implementation, acceptance, release, or production evidence.

## Phase B chain reconciled

The accepted M19 sequence is:

- M19.1 #267 / #268 / #269: read-only Graph API and server-side ACL;
- M19.2 #270 / #271 / #272: Graphology adapter and renderer-neutral boundary;
- M19.3 #273 / #274 / #275: Sigma.js v3 read-only explorer shell;
- M19.4 #276 / #277 / #278: deterministic search, focus, neighborhood, and filters;
- M19.5 #279 / #280 / #281: release-bound detail and approved provenance panels;
- M19.6 #282 / #283 / #284: deterministic layout, overview, semantic zoom, progressive pages, and 1k/10k/50k budgets;
- M19.7 #285 / #288: security, accessibility, authority, and integrated acceptance.

Every predecessor issue was closed before M19.7 implementation began. M19.7 did not rewrite predecessor implementation cores.

## Implementation scope

PR #288 changed exactly seven files:

1. the M19.7 exact-head workflow;
2. the Phase B acceptance architecture contract;
3. the isolated acceptance source scanner;
4. the graph-explorer package export and script surface;
5. the isolated acceptance contract module;
6. nine accessibility, release-view, authority, and bound tests;
7. the TypeScript compile include.

The PR added no runtime dependency and did not modify Graph API implementation, Graphology adapter implementation, Sigma shell implementation, search/filter implementation, detail implementation, scale implementation, or dependency lockfiles. The PR had no conversation comments, submitted reviews, or inline review threads before merge.

## Exact-head implementation evidence

All eight workflows completed successfully against exact implementation head `9ca1385a7a7afbe84fd4f2fe8d31be0b400681b4`:

- CI run `29240695616` (#606);
- M17 Architecture Canon Acceptance run `29240695564` (#27);
- M18 Graph v2 acceptance run `29240695513` (#42);
- M19.3 Sigma explorer shell run `29240695540` (#11);
- M19.4 graph explorer interactions run `29240695617` (#9);
- M19.5 detail provenance panels run `29240695505` (#7);
- M19.6 large graph strategy run `29240695578` (#5);
- M19.7 Phase B acceptance run `29240695543` (#1).

The M19.7 workflow verified the exact checked-out head, Python Graph API lint, ACL/leakage/bounds/release/read-only regressions, GET-only source authority, the nine-test Graphology adapter suite, the complete forty-test Graph Explorer suite including nine M19.7 tests, five 1k/10k/50k performance fixtures, the browser/CSP/persistence/write-back source scan, both production-runtime npm audits with zero high-severity vulnerabilities, and Python/TypeScript compilation. Repository CI independently passed full quality gates, the reference vertical slice, and the container build.

## Security and accessibility acceptance

Phase B is accepted with these fail-closed properties:

- ACL filtering occurs server-side before graph serialization;
- unauthorized endpoints cannot leak through edges;
- Graph API authority is GET-only and bounded;
- canonical graph input remains read-only and renderer-neutral;
- production, candidate-preview, and Source-preview descriptors are explicit;
- preview views carry non-production warnings;
- different release identities cannot be composed into one view;
- relation meaning includes type, direction, endpoints, readable text, and a directional symbol instead of relying on color alone;
- keyboard navigation and deterministic textual fallback remain accepted;
- graph adapter and explorer sources expose no runtime fetch, XMLHttpRequest, WebSocket, EventSource, beacon, cookie, local/session storage, IndexedDB, eval, or Function-constructor authority;
- explorer runtime dependencies remain exactly Graphology and Sigma;
- no mutation routes, browser persistence, browser network clients, or write-back targets are accepted;
- request depth, node count, edge count, payload, progressive batches, overview sizes, and 50k/250k graph ceilings remain bounded.

## Protected-state reconciliation

M19.7 and the complete Phase B sequence did not modify or promote production, candidate publication, the production pointer, R2 objects, credentials, permanent ledgers, or rollback state. No production action was dispatched.

M19 is complete after this documentation-only reconciliation PR passes its own exact-head checks and merges with expected-head protection. M20 Hybrid Retrieval remains a separate future phase. Graph Neural Retrieval remains excluded.
