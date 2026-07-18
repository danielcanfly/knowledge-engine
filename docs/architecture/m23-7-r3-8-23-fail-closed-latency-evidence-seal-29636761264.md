# M23.7 R3.8.23 Fail-Closed Latency Evidence Seal for 29636761264

This seal binds remote observation run `29636761264` at exact engine head
`fc1dca7186fa66db153489a90a7b369ca053db61` and issue #897.

The run produced a complete privacy-safe `completed_fail_closed_latency_repair`
receipt. Quality parity, target-rank parity, candidate identity, collection
schema, privacy, authority, and all strict-zero mutation gates passed.
Production retrieval remained `lexical`, and the candidate collection was
unchanged before and after observation.

The run did not pass the unchanged latency gate. The only false gate was
`worker_internal_shadow`: `1890 ms` against a maximum of `1200 ms`. The timing
breakdown was `991 ms` provider time and `899 ms` Qdrant time. Operator round
trip was `3256 ms` and remains informational only.

Accepted quality metrics were Recall@5 `0.875`, MRR@10 `0.807291666667`, and
nDCG@10 `0.851933109598`. Exact accepted target-rank parity was preserved.

Diagnostic Worker `knowledge-engine-r3-8-29636761264` was deployed and retained
with version id `03522a60-0bcc-42c0-b315-e845891538b2`. Separate deletion
authorization remains required. This seal grants no deletion authority.

This seal does not clear `blocked_pending_retrieval_quality` or
`blocked_pending_latency`, does not authorize fresh observation, production
mutation, serving, promotion, parent closure, or M23.7 closure.

The next legal step is independent reconciliation of this seal.
