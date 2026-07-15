# M23.7.1 Operational and Content-Quality Acceptance Contract

M23.7.1 freezes the contract consumed by M23.7.2. It does not execute retrieval, call a provider, query Qdrant, generate an answer, deploy a Worker, or alter production.

## Bound identities

- Engine entry: `d2d82d087d67669ab95a8ead91815f94f5ec04eb`
- Candidate release: `m23cand-c7fbec7e945e79d05d3263b0`
- Candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`
- Qdrant pilot: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points
- Source PR #19: draft/open/unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`

## Frozen suite

The contract defines 24 ordered cases, four in each class: direct fact, terminology, cross-section, provenance, ACL-negative and no-answer. M23.7.2 must preserve case IDs and order and must emit case-level ranked identities, scores and failure reasons.

## Metrics and gates

- Recall@5 floor: 0.80
- MRR@10 floor: 0.70
- nDCG@10 floor: 0.75
- provenance coverage floor: 1.00
- ACL leakage ceiling: 0.00
- no-answer false-positive ceiling: 0.10
- lexical Recall@5 regression ceiling: 0.05
- deterministic replay: mandatory

Passing these gates does not authorise activation. Semantic output remains evaluation-only and production retrieval remains lexical.

## Authority boundary

No network/provider call, semantic judge, answer generation, deployment, traffic change, production pointer, R2 mutation, Source mutation, Qdrant write/delete, permanent-ledger mutation, public Graph Explorer, credential rotation or Graph Neural Retrieval.

M23.7.2 is illegal until this submilestone is independently merged and reconciled.

Production mutation dispatched: false.
