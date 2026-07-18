# Proposed PR body

Fixes the R3.8 Qdrant latency blocker observed in run `29628930603` by partitioning the frozen 24-query batch into four concurrent six-query transport shards while preserving query identities, dense limit, ranking order, payload selector, read-only authority, strict-zero gates, and the unchanged 1200 ms worker shadow budget.
