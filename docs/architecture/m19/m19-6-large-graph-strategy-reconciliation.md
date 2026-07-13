# M19.6 Large Graph Strategy Reconciliation

Status: ready to close issue #282

## Identity chain

- M19.5 reconciled Engine base: `9c0f75237e9dc7db4e7cf2c805f477a674460a75`
- implementation issue: #282
- implementation PR: #283
- implementation expected head: `a9b6c483ba0c9112e6f3467bb8240724274d5672`
- implementation merge: `37aa7df5c09e03e83ed8adacfc74cca10f91808a`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

The reconciliation branch was created from the exact implementation merge SHA.
This PR closes #282 only after its own expected-head checks pass.

## Implementation evidence

PR #283 changed exactly seven files: the M19.6 exact-head workflow, architecture
contract, graph-explorer package export, TypeScript compilation scope, isolated
scale module, scale unit tests, and performance fixture runner. It did not modify
the existing M19.3 explorer shell, M19.4 interaction implementation, M19.5 details
controller, Graphology adapter, or dependency lockfile. The PR had no conversation
comments, submitted reviews, or inline review threads before merge.

All seven workflows completed successfully against exact implementation head
`a9b6c483ba0c9112e6f3467bb8240724274d5672`:

- CI run `29239525210` (#602);
- M17 Architecture Canon Acceptance run `29239525482` (#25);
- M18 Graph v2 acceptance run `29239525473` (#38);
- M19.3 Sigma explorer shell run `29239525480` (#9);
- M19.4 graph explorer interactions run `29239525883` (#7);
- M19.5 detail provenance panels run `29239525734` (#5);
- M19.6 large graph strategy run `29239525237` (#1).

The M19.6 workflow verified the exact checked-out head, the nine-test M19.2
Graphology adapter regression suite, the complete thirty-one-test graph explorer
package including nine M19.6 scale tests, five synthetic scale fixtures, and both
production-runtime npm audits with zero high-severity vulnerabilities. Repository
quality gates, reference vertical slice, and container build also passed.

## Contract reconciled

The additive `@knowledge-os/graph-explorer/scale` module creates deterministic,
release-bound `knowledge-os-graph-layout/v1` artifacts using pinned algorithm
`knowledge-os-deterministic-hash-ring` version `1.0.0` and an explicit seed.
Coordinates remain derived materialized-view data; canonical graph validity and
Source do not depend on them.

`knowledge-os-graph-overview/v1` groups nodes deterministically by normalized
primary tag with concept-type fallback, retains bounded major groups, combines
overflow as `Other`, chooses representatives by degree and stable ID, and
aggregates bounded inter-cluster edges. Overview output contains no descriptions,
raw evidence, provenance, or reviewer identity.

Semantic zoom policies define overview, context, and detail modes with explicit
label and edge budgets. Progressive local exploration emits deterministic,
cursor-bounded one- and two-hop pages of at most 500 nodes and 1,000 edges after
bounded relation filtering.

Cross-release layouts, unsupported algorithm identity, graph count mismatch,
missing or duplicate positions, non-finite coordinates, unknown ACL-safe roots,
invalid cursors, oversized batches, more than 50,000 nodes, and more than 250,000
edges fail closed.

Performance budgets are explicit for 1,000, 10,000, and 50,000 nodes. The exact
workflow exercised 1k sparse and dense, 10k sparse and medium, and 50k sparse
fixtures. Each fixture serialized and parsed a renderer-neutral payload, imported
Graphology, materialized layout and overview, exercised semantic zoom and
progressive neighborhood planning, emitted metrics, and passed payload, timing,
memory, label-suppression, and edge-reduction budgets.

## Protected-state reconciliation

M19.6 did not modify or promote production, candidate state, the production
pointer, R2 objects, credentials, permanent ledgers, or rollback state. It added
no dependency, network client, browser persistence, server endpoint, canonical
coordinate field, authorization broadening, cross-release graph merge, M19.7
closure, or Graph Neural Retrieval. This reconciliation PR is documentation only
and dispatches no release or production action.
