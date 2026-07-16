# M23.7-R3.6 Passing Candidate Reingestion Evidence Seal

## Bound implementation

- Parent R3 issue: `#474`
- R3.6 implementation issue: `#508`
- Implementation PR: `#509`
- Implementation accepted head: `bb560fce06af035bfb132a1d1e6960762fc6a07b`
- Implementation merge: `3633cd1e67f1ad489ffcfdce8f9fe90455986114`
- Evidence-seal issue: `#510`

## Sealed operator evidence

- Status: `pass_candidate_reingestion`
- Candidate collection: `llm_wiki_m23_r3_5_candidate_8eed54902c73`
- Historical pilot collection: `llm_wiki_m23_pilot_bge_m3_1024`
- Receipt file SHA-256: `0ef4a0017ee1574d40f32c0eb11049512b78163ffc4302e34be30299817e96c6`
- Receipt self-digest: `e59569d429b61dab516a47a4922a8b767f81e789f42b28105793276b643baaa8`
- Contract SHA-256: `c888e10741d402f5214dbfe0191ff8a77730b7f8cc5f57b42bdef2efa28809ca`
- Candidate manifest SHA-256: `41c24b3103f5358874c665d6c58c4e8d6dd16efc1a254eb3a44f4932227bf345`
- Aggregate fingerprint SHA-256: `ce5ebc12f2f353a45b5a1f3a2f19c2b67dc88b91d77b11550a8b271a4bcc5df6`
- ID-set SHA-256: `907e3020819ac6fd1c50ff45a4e266f97494b1aee312a1adb00547955245d0d8`
- Seal SHA-256: `26094a68c808f084938d4dd40b842bf8ac433a0bafa7e4e156ff004f3a84d704`

## Verified operation

The operator confirmed the target collection was absent before creation, created the digest-bound candidate collection, verified named vector `default` with dimension `1024` and `Cosine`, wrote exactly `107` payload-v2 points using `wait=true` and strong ordering, and retrieved all expected IDs, payloads and vectors.

The final readback produced zero mismatches. The candidate manifest, ID set and aggregate float32 point fingerprint are bound above. Nine Qdrant calls were recorded: one absence check, one collection create, two collection-schema reads, one point upsert and four bounded full-readback batches.

No rollback was dispatched because every post-create verification gate passed.

## Mutation and privacy boundary

The historical pilot and production collections were not mutated. R2, pointer, Source and production mutations were all false. The receipt contains no credential material, service URL or hostname, raw query, raw answer or document text.

The candidate collection now exists solely for separately governed R3 live acceptance. No further Qdrant mutation, deletion or reindexing is authorised by this seal.

## Authority state

Production retrieval remains lexical. Live acceptance is not yet complete. Promotion eligibility is false and `blocked_pending_retrieval_quality` remains active.

Independent reconciliation is required before issues `#510` and `#508` may close and before the R3 live-acceptance workstream may start.
