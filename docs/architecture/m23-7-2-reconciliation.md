# M23.7.2 Reconciliation

Issue: #417. Parent: #408.

## Implementation evidence

Implementation PR #418 was accepted from exact head `654d4b5854ac2e2b4c80ea7395fc2f1b8ea2859c` and merged with expected-head squash merge `799264b8b4eea80bc0bc1fbf479faf5f17bd64c4`.

The accepted exact-head workflows were all green:

- M23.7.2 Offline Retrieval Evaluation run `29396230912` (run 1);
- CI run `29396230951` (run 842);
- R2 Release Integration run `29396230899` (run 565);
- M17 Architecture Canon Acceptance run `29396230880` (run 162);
- M18 Graph v2 acceptance run `29396230895` (run 278).

## Offline evaluation result

The deterministic offline evaluation consumed M23.7.1 contract SHA `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1` and emitted evaluation SHA `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`.

The accepted run used 64 deterministic cases, eight in each frozen query class:

- known-answer-positive;
- near-domain-negative;
- out-of-domain-negative;
- keyword-trap-negative;
- stale-source-negative;
- acl-denied-negative;
- prompt-injection-negative;
- bilingual-zh-en.

The accepted metrics were:

- Recall@5: `1.0`;
- MRR@10: `1.0`;
- nDCG@10: `1.0`;
- p95 latency: `273` ms;
- error rate: `0.0`;
- citation coverage: `1.0`;
- unsupported-claim rate: `0.0`;
- ACL violation rate: `0.0`;
- stale-source acceptance rate: `0.0`;
- prompt-injection success rate: `0.0`.

## Preserved authority boundary

No live traffic, raw user telemetry, answer generation, deployment, production pointer, R2 mutation, Source mutation, Source PR #19 merge, Qdrant write/delete, public Explorer, permanent-ledger mutation, credential rotation or Graph Neural Retrieval was dispatched.

M23.7.3 remains blocked until this reconciliation PR is merged and issue #417 is closed completed.

Production mutation dispatched: false.
