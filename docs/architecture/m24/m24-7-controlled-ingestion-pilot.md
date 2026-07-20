# M24.7 Controlled Ingestion Pilot

P4 establishes the controlled ingestion pilot lane after P1-P3. It proves that
bounded, generic, candidate-only pilot batches can be planned and replayed
against the canonical M24 candidate release without mutating canonical Source or
production systems.

## Inputs

- Release ID: `20260720T160000Z-46137c97263e`
- Manifest SHA-256:
  `ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`
- Source snapshot artifact SHA-256:
  `c2150569ee59f460f64ece3ddd2deb0c27908d079fb5ac9d91722d0cd3edfd3c`

The pilot inventory is derived from the canonical provenance sources already
present in the P2/P3 release. External source URIs are represented by bounded
URI digests and logical snapshot identity, not by raw mutable connector state.

## Pilot Batches

P4 records three consecutive generic pilot manifests:

- `m24-p4-pilot-batch-001`: 3 sources;
- `m24-p4-pilot-batch-002`: 2 sources;
- `m24-p4-pilot-batch-003`: 2 sources.

Each manifest has deterministic identity, an idempotency key, review capacity
limits, allowed candidate-only actions, and explicit disallowed mutations.

## Evidence

The committed evidence is stored in:

- `pilot/m24/controlled-ingestion-pilot/batches/`;
- `pilot/m24/controlled-ingestion-pilot/m24-p4-controlled-ingestion-pilot.json`.

The evidence proves:

- immutable source snapshot identity exists for each pilot source;
- normalization, parsing, locator checks, duplicate checks, contradiction
  checks, review-packet construction, and deterministic replay complete;
- failure recovery, rollback, and deletion/tombstone drills are represented as
  dry-run candidate-only receipts;
- no manual recovery ritual or unbounded repair is required.

## Boundary

P4 does not authorize large-scale ingestion.

- no automatic canonical Source mutation;
- no Source PR content write;
- no automatic canonical approval;
- no candidate release rebuild;
- no production pointer, R2, Qdrant, credential, traffic, or permanent-ledger
  mutation.

Large-scale ingestion remains blocked until the separate readiness gate records
generic retry/dead-letter behavior, resumability, deletion propagation,
precision targets, review sampling rules, measured human review throughput,
queue SLA, cost/storage budgets, alerting, and backpressure.
