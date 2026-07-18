# M23.7 R3.8 Parallel Qdrant Batch Repair

Run `29628930603` preserved quality and strict-zero gates but measured `1835 ms` inside the Qdrant phase and `2371 ms` worker shadow latency against the unchanged `1200 ms` budget.

This bounded repair preserves the 24 frozen query identities, BGE-M3 embeddings, candidate collection, dense limit 50, payload selector, ranking order, read-only authority, strict-zero gates, and existing single-query fallback. The remote runtime now partitions the 24 vectors into four six-query Qdrant batch requests and dispatches those shards concurrently. Results are parsed per shard and concatenated in original query order.

The existing exported `executeObservation` remains the one-batch compatibility surface used by the established unit tests. The deployed request handler uses `executeParallelObservation`. External-call accounting retains one logical Qdrant batch operation because the four requests are transport shards of the same frozen 24-query observation, not independent observations.

No production retrieval, pointer, R2, collection, index, payload, quality threshold, or latency threshold is modified.
