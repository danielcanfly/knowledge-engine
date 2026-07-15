# M23.7.4 Reconciliation

Issue: #423. Parent: #408.

## Accepted implementation

Implementation PR #428 was accepted from exact head `5d7ad13657274a0ac4113796c3587cf5655503d7` and merged by expected-head squash merge as `8e9c59a468e8046ce06abc2e6d2bb064a3a6797c`.

The accepted implementation adds:

- a provider-neutral candidate composition protocol and deterministic offline provider fixture;
- exact adapter, provider, model revision, prompt, response schema, token, timeout, retry, pricing and cost identities;
- candidate-only answers composed from authorised, fresh and prompt-injection-isolated evidence;
- readable citations with exact section, parent, release, manifest, evidence digest and byte-span provenance;
- claim-to-evidence validation that rejects unsupported text and citation mismatch;
- mandatory abstention for all negative, ACL-denied, stale-source and prompt-injection cases;
- bounded provider and validation failure isolation;
- digest-only durable reports without raw user query or raw candidate answer retention;
- candidate answers that remain non-authoritative, unserved and discarded after validation.

## Entry repair

M23.7.4 entry validation discovered M23.7.3 evidence-hash instability across Python runtimes. Issue #425 repaired that prerequisite before implementation continued:

- repair implementation PR #426 merge: `04388c63e269dbe0e21be56df85e8090e9ef84cb`;
- repair reconciliation PR #427 merge: `e63c3da543ae425798b0fb43b8c1e0a6ce20bc4b`;
- stable Python 3.11/3.12 replay SHA: `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`.

The repair changed only the canonical representation of floating-point metrics entering the evidence hash. It did not change accepted retrieval metrics, lexical authority or production state.

## Exact-head CI evidence

All workflows triggered for implementation exact head `5d7ad13657274a0ac4113796c3587cf5655503d7` completed successfully. Key accepted runs include:

- M23.7.4 Candidate Grounded Answer run `29400183263` (run 11);
- CI run `29400183179` (run 870);
- R2 Release Integration run `29400183182` (run 585);
- R2 Canary run `29400183221` (run 251);
- M17 Architecture Canon Acceptance run `29400183199` (run 184);
- M17 Independent Operator GA Acceptance run `29400183335` (run 20);
- M17 GA Evidence Matrix Acceptance run `29400183234` (run 21);
- M18 Graph v2 acceptance run `29400183247` (run 306);
- M16 Security Contract Acceptance run `29400183183` (run 41);
- M16 ACL and Injection Security Acceptance run `29400183258` (run 40);
- M16 Replay and Recovery Objectives Acceptance run `29400183206` (run 31);
- M16 End-to-End Restore Drill Acceptance run `29400183215` (run 29);
- M23.6.5 Candidate Semantic Runtime run `29400183269` (run 6).

The remaining exact-head workflows for M16, M17, M23.2 through M23.6 and operator tooling also completed successfully. No review comments or unresolved review threads were present on PR #428 at merge time.

## Deterministic composition evidence

The accepted report consumed:

- M23.7.1 contract SHA `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 evaluation SHA `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- repaired M23.7.3 replay SHA `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`;
- candidate release `m23cand-c7fbec7e945e79d05d3263b0`;
- candidate manifest `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`.

Accepted identities:

- candidate composition SHA: `6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7`;
- composer identity SHA: `f014f85bb35e28787a77c78a5e647361b75dd440b39bc415802790900e847e0d`;
- prompt SHA: `3d5afc43c2c64cb8e9b9e5b86403c969ecce61224c3b0145324a9328fc7ab986`;
- response schema SHA: `78e939d7dab9ed93b7530bf631b7546fb5840b79d39f6d4cd7b37e2ab0e3463d`.

Accepted results:

- cases: `64`, eight in each frozen query class;
- grounded candidate answers: `16`;
- abstentions: `48`;
- positive answer rate: `1.0`;
- negative abstention rate: `1.0`;
- grounded validation pass rate: `1.0`;
- citation coverage: `1.0`;
- unsupported-claim rate: `0.0`;
- citation-mismatch rate: `0.0`;
- prompt-injection success rate: `0.0`;
- candidate-answer influence rate: `0.0`;
- provider failure-isolation rate: `1.0`;
- candidate p95 composition latency: `705 ms`;
- total estimated cost: `168` micro-USD;
- maximum estimated per-case cost: `11` micro-USD;
- durable answer digests: `16`;
- raw candidate answers persisted: `false`.

## Preserved authority and privacy boundary

Production retrieval remains lexical. Candidate answers are candidate-only, are never response-authoritative, are never served and are discarded after validation. No live provider call, live traffic, production query mirroring, raw user query or raw candidate answer retention, deployment, production pointer, R2 mutation, Source mutation, Source PR #19 merge, Qdrant write/delete, public Graph Explorer, permanent-ledger mutation, credential rotation, promotion decision or Graph Neural Retrieval was dispatched.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

M23.7.5 may not begin until this reconciliation is merged, issue #423 is closed completed, and a separate explicit milestone authorises privacy-safe bounded live shadow observation.

Production mutation dispatched: false.
