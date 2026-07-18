# Rationale

A single oversized 24-vector JSON request produced 1835 ms of Qdrant time. Four concurrent six-vector requests reduce per-request serialization and scheduling weight while preserving the frozen query set and deterministic concatenation order.
