# M23.7-R3.6 Guarded Candidate Reingestion

## Decision

R3.5 passed all frozen offline retrieval-quality gates. R3.6 authorises one separately governed, non-production Qdrant candidate collection so the accepted payload-v2 corpus can be observed through the real retrieval path before any blocker clearance or production decision.

## Frozen entry identities

- Parent R3 issue: `#474`
- R3.6 implementation issue: `#508`
- Entry engine: `b5501e8171f87ed25c937c245abc97e77fc32a28`
- R3.5 implementation merge: `dd10d66083a3a4b81546467f26f0f3253b3a8a22`
- R3.5 report file SHA-256: `7a84c7e98b6e50d294b5bbbe1433e61f627f1550e740d0e50e8c57994cba5f36`
- R3.5 canonical report SHA-256: `410a5781504d2906f96191627e4e5cae46bb6eb1fa5dc907c1e84ec111c01bc2`
- R3.5 candidate artifact SHA-256: `8eed54902c73314ac2e5d5e187a788e44941dae250d9823d45b71ec57d1e1371`
- R3.5 evidence seal SHA-256: `811942ecb900daba1fdde8ebd4baa33e6e31e8dd5e69ecbd44115f5b79dcf3a8`
- R3.5 reconciliation SHA-256: `fcb9cff2332865a0f2b5cd5b1ee27fbf488980fa343d16e117e9c3d4dd8cfc5d`
- Frozen evidence SHA-256: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`
- R3.6 contract SHA-256: `c888e10741d402f5214dbfe0191ff8a77730b7f8cc5f57b42bdef2efa28809ca`

## Candidate collection identity

The collection name is derived from the accepted R3.5 candidate artifact:

`llm_wiki_m23_r3_5_candidate_8eed54902c73`

It is distinct from the historical pilot collection `llm_wiki_m23_pilot_bge_m3_1024`.

The target must not exist before execution. An existing collection is rejected even when empty, because collection identity reuse would weaken provenance and rollback safety.

## Write sequence

1. Verify frozen evidence and R3.5 candidate identities.
2. Rebuild exactly 107 deterministic payload-v2 points.
3. Confirm the candidate collection is absent.
4. Create named vector `default`, dimension `1024`, distance `Cosine`, without sparse vectors.
5. Read the empty collection schema back and verify it.
6. Upsert exactly 107 points with `wait=true` and `ordering=strong`.
7. Retrieve all expected IDs in bounded batches with payloads and named vectors.
8. Compare exact ID sets, float32 vector fingerprints, payload fingerprints, aggregate fingerprint, final schema and point count.
9. Persist a privacy-safe receipt.

## Payload authority

Every point remains payload schema v2, noncanonical, not candidate-release eligible, without production authority, limited to R3 live acceptance, and bound to the R3.5 candidate artifact and R3.6 issue.

## Fail-closed rollback

If collection creation succeeds but any later verification fails, the operator attempts deletion only of the exact derived candidate collection. The rollback must verify that the candidate collection is absent afterward.

The operator has no deletion path for the historical pilot or a production collection. A rollback failure is a critical exit and does not authorise another write attempt without separate diagnosis.

## Authority boundary

R3.6 does not mutate the historical pilot or any production collection; mutate R2, pointer, Source or production; enable candidate serving or user traffic; claim R3 live acceptance; clear `blocked_pending_retrieval_quality`; grant promotion eligibility; or close R3 or M23.7.

Production retrieval remains lexical. A successful, sealed and reconciled R3.6 result authorises only a separately governed R3 live acceptance against the reconciled candidate collection.
