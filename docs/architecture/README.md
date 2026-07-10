# Knowledge OS Architecture Canon

This page is the single canonical entry point for the implemented Knowledge OS architecture.

The canon is descriptive, not an authorization surface. It explains the system that exists,
links every material claim to an implementation or governed evidence surface, and deliberately
does not embed current production identities. Operators must obtain current Engine, Source,
release, manifest, pointer, approval, and ledger identities from the governed evidence for the
operation they are performing.

## Authority order

When two descriptions disagree, use this order:

1. normative contracts in `danielcanfly/knowledge-os-foundation`;
2. canonical reviewed knowledge in `danielcanfly/knowledge-source`;
3. executable implementation and workflows in this repository;
4. immutable release, acceptance, and ledger evidence for the exact operation;
5. this architecture canon;
6. operator runbooks and explanatory notes.

The architecture canon must be updated when the implemented architecture changes. It must never
be used to override a contract, code path, approval decision, exact identity precondition, or
immutable evidence artifact.

## Canonical documents

| Document | Purpose | Owner |
|---|---|---|
| [Four-plane system map](m17/system-map.md) | Control, build, runtime, feedback, repository, trust, identity, storage, release, ACL, lifecycle, and authority maps | M17 architecture owner |
| [Architecture claim registry](m17/architecture-claims.json) | Machine-readable claims with exact repository paths and stable anchors | M17 architecture owner |
| `src/knowledge_engine/m17_architecture_canon.py` | Deterministic validation and tamper-evident report generation | Knowledge Engine maintainers |
| `.github/workflows/m17-architecture-canon.yml` | Exact-head architecture acceptance | Knowledge Engine maintainers |

## Source-of-truth policy

- Canonical Source is the only editable knowledge truth.
- Engine code implements contracts and compiles deterministic materialized views.
- Release artifacts, indexes, graphs, source maps, manifests, reports, and caches are derived
  artifacts. They are never edited as knowledge truth.
- A channel pointer selects an immutable release. It does not alter that release.
- Runtime answers and citations are release-bound views, not canonical knowledge.
- Feedback creates evidence and review candidates. It does not automatically rewrite Source.
- GitHub issue `#30` is a permanent governed evidence ledger, not a project notebook.
- Dynamic production identities are operation evidence and must not be copied into this canon.

## Diagram policy

Mermaid diagrams in the canon are explanatory projections of the machine-readable claim registry.
A diagram is not authoritative by itself. Every node, edge, boundary, and authority statement must
be supported by a claim whose reference resolves to an existing path and anchor.

Diagrams must:

- distinguish the four planes;
- mark canonical, immutable, derived, cached, and advisory data;
- show trust and mutation boundaries;
- avoid secrets, raw private content, object URIs, credentials, and production identities;
- avoid implying authority that the referenced implementation does not possess.

## Architecture document ownership

The M17 architecture owner maintains this index, the system map, and the claim registry.
Code owners maintain implementation anchors. A change that deletes or materially changes an anchor
must update the claim registry in the same pull request. CI fails closed on missing paths, missing
anchors, incomplete plane/model coverage, path escapes, duplicate claim IDs, stale dynamic
identities, or report-digest mismatch.

Future runbooks may explain operations, but they may not modify the architecture canon's authority
boundaries. Any mutating runbook must separately state actor authority, explicit approval,
operation identity, exact expected-previous identity, replay protection, verification, rollback,
and stop conditions.

## Validation

Run from the repository root:

```bash
python scripts/m17_architecture_acceptance.py \
  --registry docs/architecture/m17/architecture-claims.json \
  --output .artifacts/m17/architecture-canon-report.json
```

A passing report is deterministic for the same repository tree and registry content. It contains
the registry digest, covered planes and models, reference counts, stable issue codes, and its own
SHA-256 artifact identity.
