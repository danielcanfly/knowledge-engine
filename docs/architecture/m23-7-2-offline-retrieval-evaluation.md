# M23.7.2 Deterministic Offline Retrieval Evaluation

Parent: #408. Issue: #417.

## Scope

M23.7.2 runs a deterministic offline retrieval evaluation against the M23.7.1 contract. It does not call Qdrant, use live traffic, retain raw user telemetry, generate answers, mutate R2, change production retrieval, merge Source PR #19 or expose the Graph Explorer.

Production mutation dispatched: false.

## Entry gates

- M23.7.1 issue #414 is closed completed.
- M23.7.1 implementation PR #415 accepted head: `65565a65db3d969ae2c4d0b3d9e9e5556fc2bc7d`.
- M23.7.1 reconciliation PR #416 merge: `764182672c31b1aa71632b4e4be7327d4614fd80`.
- M23.7.1 contract SHA: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`.

## Evaluation design

The evaluation uses 64 deterministic cases, eight per frozen M23.7.1 query class:

1. known-answer-positive
2. near-domain-negative
3. out-of-domain-negative
4. keyword-trap-negative
5. stale-source-negative
6. acl-denied-negative
7. prompt-injection-negative
8. bilingual-zh-en

Positive cases require an expected document and citation. Negative, ACL, stale-source and prompt-injection cases must return no answer evidence and no citation. The evaluation measures retrieval evidence only, not answer composition.

## Metrics

The accepted offline run must satisfy the M23.7.1 thresholds:

- Recall@5 at least 0.82
- MRR@10 at least 0.68
- nDCG@10 at least 0.72
- p95 latency at most 1200 ms
- error rate exactly 0
- citation coverage exactly 1.0
- unsupported claim proxy, ACL violation, stale-source acceptance and prompt-injection success rates exactly 0

## Authority boundary

Production retrieval remains lexical, semantic output is not served to users, M23.7.3 remains blocked until M23.7.2 reconciliation, and every protected mutation remains false.

Production mutation dispatched: false.
