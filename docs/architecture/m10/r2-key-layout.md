# R2 Key Layout v1

## Namespace

All new M10 objects use:

```text
intake/v1/
```

Existing M5 keys under `raw/`, `normalized/`, and `review/` remain unchanged.

## Immutable raw blobs

```text
intake/v1/raw/sha256/{hash[0:2]}/{content_hash}
```

Properties:

- exact raw bytes;
- SHA-256 metadata required;
- `If-None-Match: *` semantics;
- an existing key with different bytes is an integrity incident;
- MIME type on the object is observed metadata only, not trusted classification.

## Snapshot envelopes

```text
intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json
```

The envelope includes the deterministic raw location and all required provenance/ACL fields. It is immutable.

## Normalized derivatives

```text
intake/v1/normalized/{snapshot_id}/{normalizer_id}/{normalizer_version}/{normalized_hash}.{ext}
intake/v1/normalized/{snapshot_id}/{normalizer_id}/{normalizer_version}/derivative.json
```

`derivative.json` binds input snapshot, tool identity, configuration digest, output object, output hash, warnings, and provenance map.

## Attempt events

```text
intake/v1/attempts/{attempt_id}/events/{sequence:06d}-{event_sha256}.json
intake/v1/attempts/{attempt_id}/result.json
```

`result.json` is written once at terminal state. It is not a mutable status file.

## Rejection evidence

```text
intake/v1/rejections/{attempt_id}/evidence.json
```

Contains sanitized metadata only unless policy explicitly permits quarantined-byte preservation. Secret values, credentials, headers, signed URLs, and raw rejected bytes are forbidden.

## Rebuildable projections

```text
intake/v1/index/source-heads/{source_id}.json
intake/v1/index/connector-cursors/{connector_type}/{cursor_id}.json
intake/v1/index/queue/{partition}/{item_id}.json
```

These objects may be mutable under compare-and-swap. They must identify their source evidence and must be reconstructable from immutable snapshots/events.

## Storage-location representation

Snapshot envelopes record:

```json
{
  "storage_location": {
    "backend": "r2",
    "bucket": "logical-config-name",
    "key": "intake/v1/raw/sha256/ab/ab...",
    "sha256": "ab..."
  }
}
```

Do not persist credentials, endpoint secrets, signed URLs, or account identifiers not required for recovery.

## Retention

M10.1 defines no deletion workflow. Raw blobs and snapshot evidence are retained. A future retention/deletion milestone must use tombstones and impact analysis rather than silent object deletion.
