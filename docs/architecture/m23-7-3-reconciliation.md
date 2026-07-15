# M23.7.3 Reconciliation

Issue: #420. Parent: #408.

## Accepted implementation

Implementation PR #421 was accepted from exact head `f48646b813f8abf6efb69e9f5f2f3fb53aaf32eb` and merged by expected-head squash merge as `b3b4b246c253a98f623e3240f6a75501327882d5`.

The implementation adds:

- a deterministic 64-case offline shadow replay across all eight frozen query classes;
- lexical-primary and frozen semantic-candidate ranked result comparison;
- exact-section and parent-article overlap, lexical-only IDs, semantic-only IDs, rank deltas, retrieval metrics and latency deltas;
- audience, ACL, freshness and prompt-injection filtering before candidate ranking;
- bounded failure probes for Qdrant timeout, dimension mismatch and release mismatch;
- query-digest-only evidence without raw query or answer retention;
- fail-closed identity, authority, privacy, safety and protected-mutation checks;
- a dedicated exact-head workflow, CLI report and targeted tests.

## Exact-head CI evidence

All 25 pull-request workflow runs associated with exact head `f48646b813f8abf6efb69e9f5f2f3fb53aaf32eb` completed successfully. Key accepted runs include:

- M23.7.3 Shadow Retrieval Replay run `29397872332` (run 3);
- CI run `29397872267` (run 848), including 1437 passing tests;
- R2 Release Integration run `29397872343` (run 569);
- R2 Canary run `29397872324` (run 249);
- M17 Architecture Canon Acceptance run `29397872303` (run 166);
- M17 Independent Operator GA Acceptance run `29397872252` (run 18);
- M17 GA Evidence Matrix Acceptance run `29397872277` (run 19);
- M18 Graph v2 acceptance run `29397872347` (run 284);
- M16 Security Contract Acceptance run `29397872311` (run 39);
- M16 ACL and Injection Security Acceptance run `29397872322` (run 38);
- M16 Replay and Recovery Objectives Acceptance run `29397872255` (run 29);
- M16 End-to-End Restore Drill Acceptance run `29397872251` (run 27);
- M23.6.5 Candidate Semantic Runtime run `29397872305` (run 4).

The remaining exact-head workflows for M16, M17, M23.2 through M23.6 and operator tooling also completed successfully.

## Repair history

The initial implementation head failed only the repository import-order lint gate. A scoped lint-policy correction was committed and re-evaluated from a new exact head. The next global CI run passed lint and 1436 existing tests but exposed one strict floating-point equality assertion in the new replay test (`0.8000000000000002` versus `0.8`). The assertion was corrected to use `pytest.approx(0.8)` without changing replay behavior, report values or authority boundaries. The final exact head then passed the complete workflow matrix.

During M23.7.4 entry verification, issue #425 found that the replay evidence identity was not portable across supported Python runtimes. Python 3.11 emitted `0d4ac3763ba0b5b5661a25273487654d2dd335d376b3a4b84cc754dda4fe4d9d`, while Python 3.12 emitted `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`. The difference came from runtime-specific floating-point summation tails entering the evidence hash. Metric floats are now canonicalised to fixed precision before threshold evaluation and hashing. A permanent Python 3.11/3.12 matrix and regression assertion both pin `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`. The accepted metrics, lexical authority and production state did not change.

No review comments or unresolved review threads were present on PR #421 at merge time.

## Deterministic replay evidence

The accepted report consumed:

- M23.7.1 contract SHA `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 evaluation SHA `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- engine entry SHA `0dba2ee821e4a5f84624938b3c552c35662a54d6`;
- candidate release `m23cand-c7fbec7e945e79d05d3263b0`;
- candidate manifest `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`.

The deterministic executable shadow replay SHA is `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`.

Accepted results:

- cases: `64`, eight in each frozen query class;
- candidate Recall@5: `1.0`;
- candidate MRR@10: `1.0`;
- candidate nDCG@10: `1.0`;
- lexical p95 latency: `93 ms`;
- candidate p95 latency: `295 ms`;
- p95 latency delta: `202 ms`;
- overall mean overlap@5: `0.95`;
- positive exact-section mean overlap@5: `0.8`;
- positive parent-article mean overlap@5: `1.0`;
- lexical-only IDs: `16`;
- semantic-only IDs: `16`;
- error, ACL violation, stale-source acceptance, prompt-injection success and semantic-output-influence rates: `0.0`;
- bounded failure-isolation success rate: `1.0`.

## Preserved authority and privacy boundary

Production retrieval remains lexical. Candidate outputs are discarded after comparison and cannot influence authoritative results. No live traffic, production query mirroring, raw user query retention, answer generation, deployment, production pointer, R2 mutation, Source mutation, Source PR #19 merge, Qdrant write/delete, public Graph Explorer, permanent-ledger mutation, credential rotation, promotion decision or Graph Neural Retrieval was dispatched.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

M23.7.4 may not begin until this identity repair is independently reconciled and issue #425 is closed completed.

Production mutation dispatched: false.
