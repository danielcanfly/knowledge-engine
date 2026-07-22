# M25.2 Unified Intake, Normalization, and Batch Orchestrator

**Predecessor status:** `m25_1_architecture_freeze_accepted`  
**Target status:** `m25_2_intake_orchestrator_accepted`  
**Entry Engine SHA:** `8830a59d34dc0df9305b53f9bbb9eff63e03d225`

## Decision

M25.2 implements one bounded admission orchestrator. It composes the accepted M10 `intake/v1`
evidence plane with the M21.2 `m21_resumable_batch` planning and checkpoint semantics. It does
not create another raw, snapshot, derivative, queue, scheduler, or worker system.

`intake/v1` remains the only location for raw bytes, immutable snapshots, normalized Markdown,
derivative metadata, intake events, and intake rejections. `admission/v1` stores only control-plane
artifacts: source inventories, adapter and authority envelopes, deterministic plans, batch manifests,
checkpoints, candidate-only normalized references, and denominator reports.

## Operator surfaces

The importable API is `knowledge_engine.m25_intake_orchestrator`. The operator command is:

```text
knowledge-m25-admission prepare ...
knowledge-m25-admission resume ...
knowledge-m25-admission status ...
```

`prepare` validates the complete descriptor population, performs deterministic local-file preflight,
builds the approved adapter registry, creates byte- and source-bounded batches, initializes the M25
and M21 checkpoints, and persists the plan bundle. `resume` reads the latest checkpoint head and
executes only a bounded number of actionable items. `status` reads the latest checkpoint without
executing work.

## Approved adapters

- `m25_adapter_intake_v1_local_markdown` reads only an explicitly supplied `allowed_root`, then
  delegates acquisition, immutable storage, policy enforcement, and normalization to M10
  `intake_local_markdown`.
- `m25_adapter_intake_v1_existing_ref` verifies explicitly supplied accepted `intake/v1` object
  references and creates a candidate-only normalized reference without copying source payloads.

Every adapter declares its reads and writes, is pinned to the accepted Engine, Source, and Foundation
identities, and forbids hidden I/O. An unapproved adapter is represented as an explicit blocked item.
It is never silently ignored.

## Determinism and batching

Stable inventory, item, plan, batch, checkpoint, adapter, authority, output, and report identities use
M10 canonical JSON bytes and SHA-256. The same descriptors, policy evidence, timestamps, and source
bytes produce byte-identical artifacts.

The M21.2 stable item identity and checkpoint transition engine are reused directly. M25.2 adds a
versioned adapter layer that packs actionable items by both `max_sources_per_batch` and
`max_bytes_per_batch`. No batch may exceed either bound. A source larger than the byte bound becomes
an explicit `SOURCE_EXCEEDS_BATCH_BYTES` block.

## Resume and retry boundary

Checkpoint updates are immutable and revisioned. `HEAD.json` is updated with compare-and-swap, and a
stale writer fails closed. Retries are limited by the admission plan and the inherited M21 maximum.
A retryable item that reaches the limit becomes an explicit `RETRY_ATTEMPTS_EXHAUSTED` block. There
is no continuous unbounded queue, background loop, or implicit scheduler.

## Full-population integrity

There is **no silent exclusion**. Every inventory item has exactly one M25 state:

- `planned`
- `acquiring`
- `retryable`
- `snapshotted`
- `normalized`
- `blocked`
- `rejected`

The batch plan separately records all preflight blocks. The final report proves:

```text
inventory_source_count
= terminal_source_count + actionable_source_count + in_flight_source_count
```

A report is ready for M25.3 only when coverage is complete, no item is actionable or in flight, every
executable item is normalized, and no source was silently excluded.

## Fail-closed policy

Unresolved ACL, unresolved owner evidence, unresolved licence evidence, invalid audience policy,
missing adapter authority, byte-identity drift, immutable collisions, stale checkpoint revisions,
and missing `intake/v1` artifacts fail closed with a reason code and evidence. Policy-blocked items
remain in the denominator and cannot enter extraction.

## Authority boundary

M25.2 permits immutable intake writes and candidate-only admission references. It performs no live
extraction, model call, review decision, canonical adoption, Source mutation, Foundation mutation,
release mutation, production pointer mutation, R2 production mutation, Qdrant mutation,
semantic/hybrid serving, production answer serving, or large-scale ingestion authorization.

The only legal successor after accepted reconciliation is M25.3 Provider-Neutral Model Extraction.
