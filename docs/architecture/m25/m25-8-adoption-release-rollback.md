# M25.8 Adoption, Candidate Release and Rollback

Status: `implementation_ready_live_adoption_blocked`

## Purpose

M25.8 proves that an exact Daniel-approved Source PR can be merged by expected head, compiled into a non-production candidate release, exercised through Search, Wiki, Graph, Sources and Vault, and rolled back without changing production authority.

## Current entry condition

The accepted M25.7 batch is benchmark-only. It closed 30/30 fixtures as `benchmark_only_reject` / `no_write`, created no Source PR and granted no M25.8 authority. Those fixtures cannot be reused as live knowledge.

The live readiness state is therefore:

`blocked_awaiting_real_approved_source_pr`

## Two separate authorities

M25.7 authority permits preparation and opening of an exact Source PR. M25.8 requires a new authority record that binds:

- exact Source repository;
- exact PR number;
- exact base SHA;
- exact head SHA;
- exact M25.7 plan SHA-256;
- explicit Source merge approval;
- explicit candidate-release build approval;
- explicit denial of production pointer and production-release authority.

A stale, synthetic or broader approval fails closed.

## Five-surface acceptance

Every candidate release must pass release-pinned regression evidence for exactly:

1. Search
2. Wiki
3. Graph
4. Sources
5. Vault

All reports must bind the same candidate release ID and manifest SHA-256. Missing, duplicated, stale or failed surface evidence blocks completion.

## Rollback

The rollback drill is candidate-only. It must restore the previous candidate identity and prove that the production pointer digest is byte-identical before and after the drill.

The drill cannot mutate:

- production pointer;
- production release;
- R2 production objects;
- Qdrant;
- traffic;
- credentials.

## CLI

```text
knowledge-m25-adoption evaluate-gate \
  --predecessor pilot/m25/m25-7-benchmark-closure.json \
  --output /tmp/m25-8-readiness-gate.json

knowledge-m25-adoption validate \
  --evidence pilot/m25/m25-8-adoption-evidence.synthetic.json \
  --output /tmp/m25-8-adoption-receipt.json
```

The CLI validates evidence and emits deterministic receipts. It does not merge Source, deploy a release or mutate any external system.

## Completion boundary

Only a `live` receipt with status `m25_8_adoption_release_rollback_complete` may support M25.8 closure. The synthetic receipt proves contract behavior only and does not authorize M25.9.
