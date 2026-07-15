# M23.6.3 First Non-Production Pilot Upsert and Readback Reconciliation

## Outcome

M23.6.3 completed the first explicitly authorised write into the isolated non-production Qdrant pilot collection and verified the complete 107-point readback.

- collection: `llm_wiki_m23_pilot_bge_m3_1024`
- vector: `default`, dimension `1024`, distance `Cosine`
- implementation issue: `#393`
- implementation PR: `#394`
- accepted implementation head: `ae9dee012b0dcd12f4844c995a6b71cb5c2e5754`
- implementation merge commit: `152f8b41b4dc5aedd7e96b77a86a0ea6d60e93ab`
- accepted CI run: `29389501184` (`CI #795`), success

## Authorisation and preflight

The operator explicitly authorised only the first 107-point upsert into the exact non-production collection above.

The immediate preflight and the write-time preflight both confirmed:

- collection status `green`;
- `points_count = 0`;
- `indexed_vectors_count = 0`;
- named vector `default` with size `1024` and `Cosine` distance;
- no sparse vectors.

The write runner was configured to refuse a non-empty collection or any schema drift.

## Frozen artifact identities

- ingestion manifest SHA-256: `2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868`
- Qdrant points artifact SHA-256: `0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b`
- point IDs SHA-256: `907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8`
- aggregate point fingerprint SHA-256: `2b726f1b37ceb4b674752e25494abc9e4cb397b2d506452b9d7a94568d50bfd3`
- release ID: `m23pilot-a07eb79e381ca7e635cc9139`
- release manifest SHA-256: `a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`

## Real operation evidence

The real external operation ran from `2026-07-15T04:47:13.053219Z` to `2026-07-15T04:47:26.394380Z`.

- upsert wait semantics: `true`
- ordering: `strong`
- Qdrant operation ID: `7`
- operation result: `completed`
- network calls: `7`
- postflight collection status: `green`
- postflight points: `107`
- unique readback IDs: `107`
- every expected ID present: `true`
- every payload and vector matched: `true`
- readback aggregate fingerprint matched the frozen artifact: `true`

The redacted receipt is committed at `pilot/m23/m23-6-3-first-upsert-receipt.json` with SHA-256 `0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b` and byte length `1975`.

## Authority boundary preserved

The 107 Qdrant points remain derived, non-canonical pilot material:

- `canonical_knowledge = false`
- `candidate_release_eligible = false`
- `production_authority = false`

The receipt records all of the following as false:

- production mutation;
- Source mutation;
- R2 mutation;
- pointer mutation;
- permanent-ledger mutation;
- deletion dispatch.

No credential material or service URL was recorded. Production retrieval remains lexical. Source PR `knowledge-source#19` remains draft, open and unmerged at head `deb3ad1e631c2149183d10561fbceb0a1848a989`. Graph Neural Retrieval remains forbidden.

## Next legal action

M23.6.4 may build bounded Worker and Queue incremental-ingestion machinery against the pilot contract. It must not mutate production retrieval, production R2 or pointer state, canonical Source, permanent ledgers, or public Graph Explorer surfaces.

Production mutation dispatched: false.
