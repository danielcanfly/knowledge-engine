# M23.7.1 Operational and Content-Quality Acceptance Contract

Parent: #408. Issue: #414.

## Scope

M23.7.1 freezes the operational and content-quality contract that all later M23.7 evaluation work must obey. It does not run retrieval evaluation, generate answers, deploy Workers, mutate R2, write Qdrant, change production traffic, merge Source PR #19 or expose the Graph Explorer.

Production mutation dispatched: false.

## Frozen entry identities

- Engine entry: `d2d82d087d67669ab95a8ead91815f94f5ec04eb`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.6 acceptance matrix: `23060cf974e01da874b75d678b2a0e8de3c6885b681e46fcaf3621a5d1036bcb`
- Candidate release: `m23cand-c7fbec7e945e79d05d3263b0`
- Candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`
- Qdrant pilot: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points
- Source PR #19: draft, open, unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`

## Evaluation contract

The contract is deterministic and offline. It forbids live traffic, raw user query retention, answer generation before M23.7.4, semantic output served to users and candidate dependency for rollback.

The acceptance thresholds are pinned in `src/knowledge_engine/m23_7_acceptance_contract.py`:

- Recall@5 at least 0.82
- MRR@10 at least 0.68
- nDCG@10 at least 0.72
- p95 latency at most 1200 ms
- error rate exactly 0
- citation coverage exactly 1.0
- unsupported claim, ACL violation and prompt injection success rates exactly 0

## Query partitions

M23.7.2 must use hidden deterministic classes:

1. known-answer-positive
2. near-domain-negative
3. out-of-domain-negative
4. keyword-trap-negative
5. stale-source-negative
6. acl-denied-negative
7. prompt-injection-negative
8. bilingual-zh-en

Every class is hidden from the candidate builder and has an explicit answer or non-answer oracle.

## M23.7.2 gate

M23.7.2 may not begin until M23.7.1 implementation is merged, M23.7.1 reconciliation is merged, issue #414 is closed completed and the contract SHA is pinned in the next issue.

## Authority boundary

All protected mutations remain false: deployment, traffic, production pointer, R2 mutation, Source mutation, Source PR #19 merge, Qdrant write/delete, answer generation, public Explorer, permanent ledger, credential rotation and Graph Neural Retrieval.

Production mutation dispatched: false.
