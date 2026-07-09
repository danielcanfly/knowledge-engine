# M13 Multi-Batch Production Operations

Implementation is tracked under the M13 parent issue and slice issues. This directory contains architecture contracts and closure evidence for multi-batch operations.

## Slices

1. [M13.1 Architecture and Identity Contracts](m13-1-identity-contracts.md)
2. [M13.2 Batch Registry and Lifecycle Planner](m13-2-batch-registry-planner.md)
3. M13.3 Concurrency Coordinator and Single Production Mutation
4. M13.4 Retention, Supersession, Abandonment and Rebuild Rules
5. M13.5 Deterministic Release Comparison
6. M13.6 Operator Status, Lookup and Closeout Tools
7. M13.7 Three-Batch Acceptance and M13 Closure

## M13 invariant

M13 may plan and evaluate multiple batches concurrently, but only one production mutation may proceed at a time, and every mutation must carry an exact expected-previous production identity.
