# M11.1 Knowledge Compiler Architecture and Contracts

Status: proposed
Milestone: M11 — Knowledge Compiler and Source Curation Productization
Parent issue: #146
Architecture issue: #147
Baseline Engine: `d5e3e2f364ba10c0de4c4a4d98389ba0ac8fa33e`
Production mutation: forbidden

M11 productizes the path from an admitted immutable M10 evidence object to a validated, reviewer-ready Source proposal. It does not replace canonical Knowledge Source, bypass human review, build a candidate release, or mutate production.

## Pipeline

```text
M10 accepted snapshot + derivative
→ admit
→ structure
→ extract
→ resolve
→ synthesize
→ validate
→ review_ready
→ separate human Source workflow
```

The compiler is a deterministic evidence transformer. Model output, when later introduced, is only a proposal and never an authority.

## Contract files

- `../../../schemas/compiler-input-v1.schema.json`
- `../../../schemas/compiler-structured-block-v1.schema.json`
- `../../../schemas/compiler-source-map-v1.schema.json`
- `../../../schemas/compiler-extraction-candidate-v1.schema.json`
- `../../../schemas/compiler-resolution-v1.schema.json`
- `../../../schemas/compiler-synthesis-proposal-v1.schema.json`
- `examples/compiler-input-v1.example.json`

## Architecture documents

- `compiler-architecture.md`
- `state-machine-and-identities.md`
- `reuse-and-migration-map.md`
- `review-boundary.md`
- `test-strategy-and-acceptance.md`

## Governing invariants

1. Compiler input is bound to exact M10 snapshot, derivative, admission, connector, normalizer, ACL, owner, license, and hash identities.
2. Every extracted or synthesized statement retains exact source-map evidence.
3. Audience and access policy may stay equal or become more restrictive, never broader.
4. Unresolved ACL or license cannot silently become compilation-ready public knowledge.
5. Duplicate, contradiction, supersession, unresolved conflict, and unsupported claim are distinct outcomes.
6. Model confidence is metadata only. It cannot authorize a claim, proposal, review, or Source change.
7. Compiler outputs are immutable review artifacts under `compiler/v1/`.
8. Canonical Source remains the only editable truth.
9. Runtime graphs, indexes, chunks, and source maps remain rebuildable derivatives.
10. Human Source review is mandatory before any canonical Source PR package can be accepted.
11. The compiler cannot write `channels/production.json`, candidate channels, releases, promotion requests, GitHub governance decisions, or permanent ledger issue #30.
12. Exact replay of the same immutable input and compiler identity produces identical IDs and bytes.

## M11.2 next slice

M11.2 will implement one deterministic local-Markdown vertical slice. It will consume an admitted M10 local-file snapshot and Markdown derivative, produce structured blocks, exact source maps, bounded deterministic extraction candidates, immutable events and a terminal review-only result. It will not invoke a model or write Source.

## Production baseline

M11.1 is architecture-only. Production must remain:

- release: `20260708T040116Z-69a9f445699a`
- manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Permanent audit ledger issue #30 must remain open and unchanged because M11.1 performs no production promotion.