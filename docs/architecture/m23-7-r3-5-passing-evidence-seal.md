# M23.7-R3.5 Passing Operator Evidence Seal

## Bound implementation

- Parent R3 issue: `#474`
- R3.5 implementation issue: `#502`
- R3.5 implementation PR: `#503`
- Implementation accepted head: `61b467ec22a74e7a42ebccb4626931a6dcfd3915`
- Implementation merge: `dd10d66083a3a4b81546467f26f0f3253b3a8a22`
- Evidence-seal issue: `#504`

## Sealed operator evidence

- Status: `pass_rank_quality_calibration`
- Operator report file SHA-256: `7a84c7e98b6e50d294b5bbbe1433e61f627f1550e740d0e50e8c57994cba5f36`
- Canonical report SHA-256: `410a5781504d2906f96191627e4e5cae46bb6eb1fa5dc907c1e84ec111c01bc2`
- Candidate artifact SHA-256: `8eed54902c73314ac2e5d5e187a788e44941dae250d9823d45b71ec57d1e1371`
- Frozen evidence SHA-256: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`
- Contract SHA-256: `3b486845009926842662fbefb197086ce6658641e27ec5bc6cc239f0506ae2bc`
- Seal SHA-256: `811942ecb900daba1fdde8ebd4baa33e6e31e8dd5e69ecbd44115f5b79dcf3a8`

## Quality result

- Recall@5: `0.875` versus `0.82`
- MRR@10: `0.807291666667` versus `0.68`
- nDCG@10: `0.851933109598` versus `0.72`
- Maximum top-10 hub frequency: `3` versus maximum `6`
- Query variants: `24/24` unique
- All report gates: passed

R3.5 preserves R3.4 Recall while materially increasing ranking quality. The calibrated hybrid raises MRR from `0.566666666667` to `0.807291666667` and nDCG from `0.643589039297` to `0.851933109598`.

The remaining terminology case `m23q-02` moved from R3.4 final rank `21` to R3.5 rank `8`. It remains outside top 5, but the frozen suite-level gates pass without target-aware scoring or threshold changes.

## External calls and privacy

- Workers AI BGE-M3 batches: `1`
- Query count: `24`
- Qdrant reads: `0`
- Qdrant writes: `0`
- Raw queries persisted: no
- Document text persisted: no
- Credentials or service URLs persisted: no

## Authority state

This seal records a completed-passed offline repair. It does not authorize Qdrant mutation, candidate reingestion, live acceptance, R2 or pointer mutation, Source mutation, deployment, serving, threshold changes, promotion, production mutation or retrieval blocker clearance.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` stays open.

## Next legal action

After expected-head merge and independent reconciliation, the next legal action is a separately governed candidate reingestion proposal. That proposal must define the candidate collection, rollback boundary, exact payload identity, live acceptance protocol and explicit no-production-authority state.
