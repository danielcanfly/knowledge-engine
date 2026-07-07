# M7 Governed Batch Spec v2

Status: `implemented`

Parent tracker: `#74`

Milestone tracker: `#76`

## Schemas

- Batch spec: `governed-batch-spec/v2`
- Registry: `governed-batch-registry/v1`
- Spec root: `governed_batches/`
- Registry path: `governed_batches/registry.json`

## Lifecycle

Legal states, in order:

1. `planned`
2. `source_reviewed`
3. `source_validated`
4. `candidate_built`
5. `runtime_accepted`
6. `request_spec_committed`
7. `production_promoted`
8. `closed`

Only the next adjacent state is a legal transition. Skipping a gate is rejected.

## Identity requirements

Every spec requires:

- safe unique `batch_id`
- non-empty Source scope
- pinned Builder SHA
- pinned Foundation SHA
- public acceptance query and citation target
- `raw_fallback_allowed: false`

From `source_reviewed` onward, Source SHA is required.

From `candidate_built` onward, candidate channel, release ID, and manifest SHA-256 are required.

From `request_spec_committed` onward, operation ID and committed production request path are required.

ACL query and expected ACL status must either both exist or both be absent.

## Registry collision rules

The registry rejects duplicates across:

- batch ID
- spec path
- candidate channel
- operation ID
- production request path

Every registered entry must match the identities in its referenced spec.

## Validation command

```bash
python -m knowledge_engine.batch_cli validate \
  --registry-path governed_batches/registry.json \
  --evidence-dir evidence
```

The command is non-mutating. It writes `batch-registry-validation.json` and does not dispatch workflows, modify Source, build candidates, or touch production.

## M7.2 boundary

M7.2 establishes the schema, lifecycle, registry, collision checks, and evidence output. The first new governed batch is intentionally deferred to M7.5 dry-run work.
