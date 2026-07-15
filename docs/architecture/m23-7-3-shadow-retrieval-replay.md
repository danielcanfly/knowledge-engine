# M23.7.3 Shadow Retrieval Replay

Parent: #408. Issue: #420.

## Scope

M23.7.3 implements a deterministic offline replay that compares lexical-authoritative retrieval with a frozen semantic candidate snapshot. It does not call live Qdrant, mirror production queries, retain raw user telemetry, generate answers, deploy an endpoint, mutate R2 or production pointers, merge Source PR #19, or change production retrieval.

Production mutation dispatched: false.

## Entry identities

- Engine main: `0dba2ee821e4a5f84624938b3c552c35662a54d6`.
- M23.7.1 contract SHA: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`.
- M23.7.2 evaluation SHA: `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`.
- M23.7.2 issue #417: closed completed.
- M23.7.2 implementation merge: `799264b8b4eea80bc0bc1fbf479faf5f17bd64c4`.
- M23.7.2 reconciliation merge: `0dba2ee821e4a5f84624938b3c552c35662a54d6`.
- Candidate release: `m23cand-c7fbec7e945e79d05d3263b0`.
- Candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`.
- Qdrant pilot collection: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points.
- Source PR #19: draft, open, unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

## Replay model

The frozen 64-case corpus preserves the eight M23.7.1 query classes. Each record stores only a test-case ID and deterministic query digest, never raw query or answer text.

```text
frozen case
  ├─ lexical primary ranking
  └─ frozen semantic candidate pipeline
       audience → ACL → freshness → prompt-injection filter → rank → threshold
            ↓
comparison receipt
            ↓
overlap@5, parent overlap, lexical-only IDs, semantic-only IDs,
rank deltas, candidate Recall/MRR/nDCG and latency deltas
            ↓
candidate result discarded; lexical result remains authoritative
```

Top-k overlap is defined as intersection size divided by the larger observed top-k list length. Empty/empty negative results count as agreement.

## Failure isolation

Bounded probes cover Qdrant timeout, dimension mismatch and release mismatch. Every probe proves that lexical primary retrieval continues, the failed candidate returns no result, arbitrary exception text is not persisted and semantic output cannot influence authority.

## Fail-closed gates

The implementation rejects identity drift, missing or duplicate cases, query-class drift, nondeterministic replay-seed drift, ranking before ACL/freshness/injection filtering, candidate misses below the frozen retrieval thresholds, candidate output retention, semantic output influence, ACL leakage, stale-source acceptance, prompt-injection success, privacy weakening or any protected mutation.

## Authority boundary

Production retrieval remains lexical. This milestone makes no promotion decision and does not authorise live shadowing, answer generation, deployment, Source adoption, Qdrant writes/deletes, public Graph Explorer or Graph Neural Retrieval.

Production mutation dispatched: false.
