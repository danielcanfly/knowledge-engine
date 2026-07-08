# Intake State Machine

## Persisted states

```text
                 +------------------------------+
                 |                              v
 discovered -> acquired -> snapshotted -> normalized -> accepted_for_compilation
      |             |            |            |
      +-------------+------------+------------+----> rejected
```

`rejected` and `accepted_for_compilation` are terminal for one attempt.

## Entities

### Source

Stable logical source tracked by `source_id`.

### Attempt

One bounded acquisition execution:

```text
attempt_id = attempt_ + ULID
```

Attempts preserve chronology and operational evidence. Repeating an exact completed request may return an idempotent prior result, but a retry after terminal rejection creates a new attempt.

### Snapshot

Immutable evidence envelope for acquired bytes and source facts.

### Derivative

Immutable normalized/extracted output bound to a snapshot and normalizer identity.

## Legal transitions

| From | To | Required evidence |
|---|---|---|
| none | discovered | connector identity, canonical locator, source_id |
| discovered | acquired | bounded complete stream, retrieval facts, observed byte count/hash |
| acquired | snapshotted | pre-snapshot safety gate passed, immutable raw blob and snapshot envelope verified |
| snapshotted | normalized | deterministic derivative, normalizer identity/version, derivative hash |
| normalized | accepted_for_compilation | ACL/license resolved, security policy passed, provenance complete |
| any nonterminal | rejected | typed reason, stage, sanitized evidence, no forbidden writes |

## Illegal transitions

- rewriting any prior state event;
- `rejected -> acquired` within the same attempt;
- `accepted_for_compilation -> normalized`;
- `discovered -> normalized`;
- acceptance with unresolved ACL or license;
- acceptance without raw-blob and snapshot-envelope integrity;
- snapshot creation after a pre-snapshot hard rejection;
- compilation admission of rejected content.

## Event record

Every transition emits immutable canonical JSON:

```json
{
  "schema_version": "intake-event/v1",
  "attempt_id": "attempt_...",
  "sequence": 3,
  "occurred_at": "2026-07-08T00:00:00Z",
  "from_state": "acquired",
  "to_state": "snapshotted",
  "actor": "knowledge-engine",
  "reason_code": "SNAPSHOT_WRITTEN",
  "evidence_refs": ["..."],
  "previous_event_sha256": "...",
  "event_sha256": "..."
}
```

The event hash excludes `event_sha256` itself. The previous-event hash creates an attempt-local append-only chain.

## Idempotency

- immutable put of identical bytes at the same key returns `already_present`;
- differing bytes at an existing immutable key is an integrity failure;
- identical snapshot identity reuses the snapshot envelope;
- normalized derivative replay must match the recorded derivative hash;
- event replay cannot append duplicate logical transition evidence;
- source-head updates use compare-and-swap and are reconstructable.

## Parent linkage

For a new snapshot of an existing source:

- `parent_snapshot` points to the prior accepted or latest governed snapshot according to policy;
- a stale parent is rejected or explicitly reconciled;
- concurrent attempts may both create immutable snapshots, but only a governed CAS update can move the source-head projection.

## Rejection behavior

Two rejection classes:

### Pre-snapshot rejection

Examples: oversized source, malware, secret policy failure, unsupported binary, path escape.

Persist sanitized metadata-only rejection evidence. Do not persist source bytes in the normal intake namespace.

### Post-snapshot rejection

Examples: normalization failure, unresolved ACL, unsupported encoding after snapshot, compilation-admission failure.

The immutable snapshot remains evidence but is quarantined and cannot enter compilation.
