# ADR-001: Immutable Intake Plane and Snapshot Identity

- Status: Proposed
- Date: 2026-07-08
- Owners: Knowledge OS operators
- Supersedes: none
- Extends: M5.1 immutable Markdown intake

## Context

M5.1 proved four valuable primitives:

- immutable content-addressed raw blobs;
- capture metadata separated from raw bytes;
- deterministic Markdown normalization;
- idempotent replay and cross-source raw-blob reuse.

It is intentionally a vertical slice. Connector acquisition, snapshot identity, normalization, security scanning, review-packet generation, and compilation admission are coupled in one Markdown-specific path. M10 must support heterogeneous connectors without creating a second editable truth or weakening ACLs.

## Decision

Create an explicit intake plane with seven separable components:

1. connector adapter;
2. acquisition coordinator;
3. pre-snapshot safety gate;
4. immutable raw-blob writer;
5. immutable snapshot-envelope writer;
6. normalizer dispatcher;
7. compilation-admission gate.

Review-packet generation remains downstream. It consumes an accepted normalized derivative and is not part of connector acquisition.

## Identity model

### `source_id`

Stable logical identity for one source across versions. It is either operator-supplied or deterministically minted from:

```text
connector_type + canonical_locator
```

Canonicalization is connector-specific and versioned. A changed source body does not change `source_id`.

### `content_hash`

Lowercase SHA-256 of the exact acquired raw bytes. It is the raw-blob identity and deduplication key.

### `snapshot_id`

Immutable evidence-envelope identity:

```text
snap_ + sha256(canonical_json(identity_payload))
```

M10 canonical JSON v1 is UTF-8 JSON with recursively sorted object keys, NFC-normalized strings, `ensure_ascii=false`, compact separators, no insignificant whitespace, and no trailing newline. Set-like arrays such as principals are sorted before serialization.

The identity payload contains:

```text
schema_version
source_id
original_uri
connector_type
connector_version
retrieved_at
content_hash
byte_size
mime_type
encoding
license
owner
audience
access_policy
source_version
parent_snapshot
```

It excludes `snapshot_id`, `storage_location`, processing status, mutable pointers, and runtime observations to avoid circular or unstable identity.

Consequences:

- identical bytes and identical evidence metadata replay to the same snapshot;
- identical bytes with different metadata share a raw blob but produce distinct snapshots;
- the same URI with changed bytes keeps `source_id` and creates a new snapshot;
- the same bytes from different URIs produce distinct source/snapshot records but share a raw blob.

### Normalized derivative identity

A derivative is identified by:

```text
derivative_id = drv_ + sha256(
  snapshot_id + normalizer_id + normalizer_version + normalized_content_hash
)
```

Normalization never overwrites raw bytes and never becomes canonical Source.

## Evidence and index layers

### Immutable evidence

- raw blobs;
- snapshot envelopes;
- normalized derivatives;
- attempt events;
- rejection evidence.

### Mutable, rebuildable indexes

- latest snapshot pointer per source;
- connector discovery cursor;
- queue status projection;
- search/index views.

Indexes may use compare-and-swap but are never evidence truth.

## Metadata persistence decision

M10 v1 uses R2 immutable JSON objects as the evidence registry because the existing object-store abstraction already supports filesystem and R2 with conditional writes. A database may later provide query projections, but it must be rebuildable from immutable evidence and cannot replace it.

## State model

Persisted lifecycle:

```text
discovered -> acquired -> snapshotted -> normalized -> accepted_for_compilation
                                              \-> rejected
```

`rejected` is terminal for an attempt. Retry creates a new `attempt_id`; it does not rewrite the prior attempt.

## Compatibility

- Existing M5 keys remain untouched.
- `capture_id` is treated as a legacy snapshot-equivalent identifier.
- M10 readers may expose a compatibility adapter for legacy captures.
- No bulk R2 migration is part of M10.1.

## Non-negotiable invariants

1. Raw bytes are immutable and addressed by SHA-256.
2. Snapshot metadata is immutable and hash-bound to its identity payload.
3. Derivation cannot broaden audience or permissions.
4. Unknown ACL or license metadata cannot become public.
5. Rejected bytes never enter compilation.
6. Connector code cannot write canonical Source or production channels.
7. Graphs, indexes, normalized files, and source-head pointers are derived views.
8. Exact replay is idempotent.
9. Every terminal failure emits sanitized evidence.
10. Production remains unchanged throughout M10.1.

## Alternatives rejected

### Use URI as snapshot identity

Rejected because URIs are mutable, can alias the same content, and do not encode retrieval or ACL evidence.

### Use only raw content hash as snapshot identity

Rejected because identical bytes can arrive with different provenance, permissions, ownership, licenses, and retrieval times.

### Store normalized Markdown as the raw record

Rejected because normalization destroys byte-exact evidence and can hide parser behavior.

### Introduce a database as the only intake registry

Rejected because it creates a mutable evidence authority and complicates deterministic recovery.

## Consequences

Positive:

- connector-independent evidence contract;
- byte-exact provenance;
- safe deduplication;
- deterministic replay;
- rebuildable projections;
- explicit ACL and rejection behavior.

Costs:

- more objects per intake;
- source-head/index reconciliation;
- connector-specific canonicalization and ACL mapping;
- explicit normalizer version management.
