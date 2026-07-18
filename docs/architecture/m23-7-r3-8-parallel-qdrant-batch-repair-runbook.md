# Runbook

1. Review PR CI on the exact head SHA.
2. Merge only with expected-head protection.
3. Dispatch `M23.7 R3.8 Remote Observation` on the resulting exact main SHA with attempt 1.
4. Compare worker shadow latency, quality, strict-zero, identity, and privacy gates against the frozen contract.
5. Seal and independently reconcile the new evidence before any blocker clearance or diagnostic Worker deletion.
