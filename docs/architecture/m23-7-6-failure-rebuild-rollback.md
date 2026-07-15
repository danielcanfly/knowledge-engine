# M23.7.6 Failure Injection, Rebuild and Lexical Rollback

Parent issue: #408. Implementation issue: #446.

## Decision

M23.7.6 is a deterministic, offline reliability proof. It does not attempt to make the
M23.7.5 semantic candidate eligible for production. It proves that bounded candidate
failures are isolated, the frozen pilot identity is rebuildable from immutable evidence,
and rollback remains immediate lexical-only operation with no candidate dependency.

The two M23.7.5 blockers remain unchanged:

- `blocked_pending_latency`;
- `blocked_pending_retrieval_quality`.

## Exact entry baseline

- Engine: `1055e4257a369246803aaf086a1124f6df872f89`;
- M23.7.1 contract: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 evaluation: `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- M23.7.3 replay: `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`;
- M23.7.4 composition: `6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7`;
- M23.7.5 final evidence: `c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71`;
- M23.7.5 outcome: `completed_fail_closed`;
- candidate release: `m23cand-c7fbec7e945e79d05d3263b0`;
- candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`;
- Source PR #19: open, draft and unmerged at
  `deb3ad1e631c2149183d10561fbceb0a1848a989`.

## Fault matrix

The deterministic matrix contains ten bounded classes:

1. Cloudflare timeout;
2. Cloudflare unavailable;
3. Qdrant timeout;
4. Qdrant unavailable;
5. collection identity drift;
6. point or release identity drift;
7. vector contract drift;
8. ACL rejection;
9. response shape drift;
10. circuit breaker open after three failures.

Every scenario is evaluated without a live network call. For each scenario the accepted
receipt proves:

- the observed failure class equals the expected bounded class;
- raw exception text is not persisted;
- candidate results are empty and discarded;
- lexical results before and after failure are byte-identical;
- lexical primary continues;
- rollback completes immediately in `lexical-only` mode;
- rollback requires no provider, vector store, Worker, Queue or candidate Runtime;
- candidate output cannot influence authority;
- no protected mutation is dispatched.

## Deterministic rebuild proof

The rebuild is an identity reconstruction only. It performs no provider call, Qdrant
read, Qdrant write, Qdrant delete, Source write, R2 mutation or pointer mutation.

The descriptor pins:

- collection `llm_wiki_m23_pilot_bge_m3_1024`;
- named vector `default`, 1024 dimensions, Cosine;
- 107 points;
- Qdrant release `m23pilot-a07eb79e381ca7e635cc9139`;
- release manifest
  `a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`;
- ingestion manifest
  `2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868`;
- points artifact
  `0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b`;
- point-ID set
  `907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8`;
- aggregate point fingerprint
  `2b726f1b37ceb4b674752e25494abc9e4cb397b2d506452b9d7a94568d50bfd3`;
- first-write receipt
  `0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b`;
- point identity strategy `uuid5(section_id,embedding_model)`;
- pending-proposal payload authority flags remain false.

Two independent calculations produce the same descriptor SHA-256:

`53e048805c60e9c08d23c67cc96e0b84ae75c0ee9fe121c1776cd28c5053e8e7`

## Rollback proof

The rollback target is always the lexical primary. Candidate output is comparison-only,
discarded and non-authoritative. Any candidate failure or identity drift leads directly
to lexical-only operation without changing production configuration because production
retrieval never left lexical mode.

This proof therefore does not execute a production rollback mutation. It proves that no
candidate dependency is required and that user-visible authoritative result IDs remain
unchanged throughout every injected failure.

## Evidence

Machine-readable receipt:

`pilot/m23/m23-7-6-failure-rebuild-rollback-evidence.json`

Receipt SHA-256:

`a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1`

## Phase gate

M23.7.7 remains blocked until the M23.7.6 implementation is merged by expected head,
an independent reconciliation PR is merged, and issue #446 is closed completed.

No promotion eligibility is granted. The M23.7.5 latency and retrieval-quality blockers
must remain visible through M23.7.7 and the final M23.7.8 decision.

## Authority boundary

No live traffic, user sampling, production query mirroring, answer serving, deployment,
production pointer, R2 mutation, Source mutation, Source PR #19 merge, Qdrant write or
delete, Worker/Queue mutation, public Graph Explorer, permanent ledger mutation,
credential rotation, promotion decision or Graph Neural Retrieval.

Production mutation dispatched: false.
