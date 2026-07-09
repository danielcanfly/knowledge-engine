# M13.5 Deterministic Release Comparison

## Purpose

M13.5 produces immutable, replayable evidence comparing one exact base production release with one exact target release or candidate. It is a read-only evaluation step and satisfies the existing M13 registry prerequisite for a completed `release_comparison` operation before a batch may request a production slot.

## Exact input boundary

A comparison request pins:

- batch ID and optional candidate channel;
- base release ID, manifest key and manifest SHA-256;
- target release ID, manifest key and manifest SHA-256;
- exact Source repository and commit for each side;
- exact builder identity and foundation SHA-256 for each side;
- expected-previous production identity;
- actor, request timestamp and generation timestamp.

There is no `latest` lookup, directory scan, raw fallback or network retrieval. Every manifest and artifact is read from an explicit object-store key and verified byte-for-byte against its declared SHA-256 and byte size.

## Release inventory contract

`m13_release_inventory.py` defines `knowledge-engine-m13-release-inventory/v1`.

A canonical manifest contains exactly one sorted inventory entry for each required artifact type:

1. `concepts`
2. `claims`
3. `audience`
4. `citations`
5. `registry`
6. `indexes`

Each entry declares its object key, SHA-256, byte size and schema version. Manifest and artifact JSON must equal the compact canonical JSON encoding used by M13 contracts. Unknown artifact types, missing singleton types, duplicate entries, unsorted inventory, schema mismatch, release mismatch and malformed or non-canonical JSON fail closed.

The exact reference also pins Source, builder and foundation identities. A manifest that differs from those expected identities is rejected as drift rather than silently accepted.

## Stable semantic comparison

`m13_release_comparison.py` compares entries by stable IDs:

| Artifact | Stable identity |
|---|---|
| concepts | `concept_id` |
| claims | `claim_id` |
| audience | `audience_id` |
| citations | `citation_id` |
| registry | `registry_id` |
| indexes | `index_id` |

Entries must be sorted and unique. Changed entries record deterministic before and after hashes plus the exact changed field names. Free-prose heuristic matching is not used.

### Audience

Audience changes are classified as `unchanged`, `narrowed` or `broadened`. Moving toward a less restrictive audience, removing required principals or introducing a new audience surface is broadening. Every broadening creates a release blocker. M13.5 reports the blocker but cannot approve it.

### Claims and citations

New claims without citation IDs are blockers. Removing citation IDs from an existing claim or removing supported claim IDs from a citation is also a blocker. Citation target substitution is recorded as a deterministic citation mutation.

### Registry and indexes

Registry entries are compared as stable canonical identities, including alias and mapping mutations. Indexes remain derived views: comparison reports declared input, count, schema and digest drift but never treats an index as editable truth.

### Manifests

Manifest comparison records Source, builder, foundation, schema and artifact-inventory changes. The base release and manifest must equal expected-previous production. The target may represent a later Source commit, but each side must independently match its exact request identity.

## Deterministic result and replay

The comparison identity is the SHA-256-derived identity of:

- the versioned request;
- every exact base input key and hash;
- every exact target input key and hash.

It yields:

- `mcompare_<32 hex>` comparison ID;
- canonical result bytes;
- canonical SHA-256;
- immutable key `m13/v1/release-comparisons/<comparison_id>/result.json`.

Replaying identical inputs returns the existing identical bytes and marks the call idempotent. Existing divergent bytes at the same key are an immutable collision and fail closed.

## M13 registry integration

`ReleaseComparisonResult.operation_result()` creates a completed existing-contract `M13OperationResult` with:

- kind `release_comparison`;
- the same batch identity;
- expected-previous production evidence;
- the immutable comparison artifact as the evidence reference;
- `planning_only=True`;
- `requires_production_slot=False`.

The result is then recorded through the existing M13 registry flow. No parallel registry or transition bypass is introduced.

## Retention integration

`ReleaseComparisonResult.retention_artifact()` classifies the immutable result as M13 `evidence`. M13.4 therefore retains it permanently. The evidence references the comparison, base release and target release identities and cannot become a physical deletion candidate.

## Explicit non-mutations

M13.5 does not:

- mutate canonical Source;
- create or mutate a candidate or release;
- acquire a production lease or permit;
- mutate production;
- execute rollback;
- delete any object;
- append permanent ledger issue #30;
- perform arbitrary network retrieval.

The production coordinator remains the only route into `promoting`.

## Failure posture

The implementation fails closed for missing objects, hash or byte-size mismatch, malformed or non-canonical JSON, release identity mismatch, Source/builder/foundation drift, unknown or duplicate artifacts, duplicate or unsorted stable IDs, stale production identity, batch/source/channel mismatch and immutable collision.
