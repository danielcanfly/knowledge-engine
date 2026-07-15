# M23.6.7 Acceptance, Closure, and Reconciliation

## Decision

M23.6.7 is the exact-evidence closure gate for the complete non-production candidate Runtime and internal Graph Explorer programme. It validates M23.6.1 through M23.6.6, including the mandatory M23.6.2a real-evidence repair, without adding deployment or production authority.

Production remains `RETRIEVAL_MODE=lexical`.

## Exact entry baseline

- Engine: `66b3086145ff17700a4996a2bedc29c908faf349`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- Parent issue: #383
- Closure issue: #405
- Source PR #19 head: `deb3ad1e631c2149183d10561fbceb0a1848a989`
- Source PR #19 state: draft, open, unmerged

## Exact milestone chain

| Stage | Issue | Implementation PR | Reconciliation PR | Accepted implementation head | Reconciliation merge |
|---|---:|---:|---:|---|---|
| M23.6.1 | #384 | #385 | #386 | `2a284811d36128ec44a16c694930e620b7ee485d` | `913c8cbb19dd6c7b89b753aecd61afd943e373fc` |
| M23.6.2 | #387 | #388 | #389 | `f9de0b5d7b351b2551f9cf68a36a31f5674acbfa` | `8fd1e00632aebb2ab5af487fbcd626e9f8f3305f` |
| M23.6.2a repair | #390 | #391 | #392 | `78cc20e1c076ce388a80553b0162f178a27d90bb` | `43b6f2b0dd39ae0e7a19fbcce81272071a279dcf` |
| M23.6.3 | #393 | #394 | #395 | `ae9dee012b0dcd12f4844c995a6b71cb5c2e5754` | `baa0fb9bf89bb216dbc34d3fb633b6eee706f029` |
| M23.6.4 | #396 | #397 | #398 | `2a5ce95d105484a77df5e5d7151c2c5e7238cd7d` | `d0fb8b1b799d91b15520fd0bf8dacd093cf91e0d` |
| M23.6.5 | #399 | #400 | #401 | `26344362436f69c041723885aced788e5de007e3` | `0eecc89bb711e7df8976a79d46bcd2d1072be44a` |
| M23.6.6 | #402 | #403 | #404 | `2a5a9ea181d0ed35f9e46b89139e2d2103b96804` | `66b3086145ff17700a4996a2bedc29c908faf349` |

Every reconciliation merge is the next stage's exact entry base. M23.6.2a is a required repair chain and cannot be omitted, reordered, or treated as duplicate evidence.

## Qdrant acceptance

The accepted non-production pilot is bound to:

- collection: `llm_wiki_m23_pilot_bge_m3_1024`;
- named vector: `default`;
- dimension and distance: `1024`, `Cosine`;
- points: `107`;
- ingestion manifest: `2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868`;
- points artifact: `0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b`;
- point ID set: `907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8`;
- aggregate fingerprint: `2b726f1b37ceb4b674752e25494abc9e4cb397b2d506452b9d7a94568d50bfd3`;
- first-write receipt: `0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b`.

The preflight collection was empty. The postflight collection contained exactly 107 points. Every expected ID, payload, and float32 vector fingerprint matched. All candidate, canonical, and production authority flags remained false.

## Candidate release and Explorer acceptance

The immutable candidate release is:

- release ID: `m23cand-c7fbec7e945e79d05d3263b0`;
- manifest identity: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`;
- Graph v2: `9e87b4ee48ad6900d5b32d493ddaa3e2d05eca1dbfb4d52b87f4bc3ef15af380`;
- 15 pending proposal nodes;
- 12 reviewed typed relationships;
- 107 semantic sections through three evidence anchors with counts 29, 40, and 38.

The evidence does not support per-concept assignment of the shared section set. Acceptance therefore requires `per_concept_section_attribution_available=false`.

Typed graph relationships and semantic neighbours remain separate layers. Semantic overlays are renderer-only, bounded, and cannot mutate Graph v2 or Graphology state.

## Runtime and rollback proof

The accepted dormant Runtime and Explorer state is:

- `CANDIDATE_RUNTIME_ENABLED=false`;
- `SHADOW_SEMANTIC_ENABLED=false`;
- `GRAPH_EXPLORER_ENABLED=false`;
- `MULTIHOP_MODE=off`;
- answer generation disabled;
- Graph Neural Retrieval disabled;
- lexical output authoritative;
- semantic output not served to production.

Rollback is immediate lexical-only operation. It requires no candidate service, vector store, Worker, Queue, Explorer, or provider dependency.

## Exact-head acceptance workflow

The dedicated workflow:

1. checks out and verifies the exact PR head;
2. runs all M23.6 Python tests and 13 new closure adversarial cases;
3. emits the closure report twice and compares the bytes;
4. replays the immutable M23.6.6 release twice;
5. validates the real Qdrant receipt and dormant authority contracts;
6. type-checks both Cloudflare Worker packages;
7. performs Wrangler dry-run validation only;
8. runs Graphology and the complete Graph Explorer suite;
9. runs 1k, 10k, and 50k performance fixtures;
10. scans CSP, browser network, persistence, and write-back surfaces;
11. audits runtime dependencies;
12. proves lexical rollback and zero protected mutations;
13. compiles the accepted Python and TypeScript scope.

## Authority boundary

M23.6.7 dispatches no Worker or Pages deployment, Access application creation, Workers AI inference, Qdrant operation, Source mutation, Source PR #19 merge, R2 write, pointer change, production traffic change, permanent-ledger mutation, deletion, credential rotation, public Graph Explorer, or Graph Neural Retrieval.

The implementation PR does not close #405 or parent #383. Closure is reserved for a separate expected-head reconciliation PR.

Production mutation dispatched: false.
