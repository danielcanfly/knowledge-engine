# M12.3 No-Mutation Invariants

M12.3 is intentionally non-mutating. The implementation and tests enforce this boundary at the artifact level.

## Invariant payload

Every baseline check includes:

```json
{
  "canonical_source_write_permitted": false,
  "candidate_write_permitted": false,
  "release_write_permitted": false,
  "production_write_permitted": false,
  "permanent_ledger_append_permitted": false
}
```

## Meaning

- The check is evidence, not approval.
- The check may block a downstream release path.
- The check cannot authorize canonical Source writes.
- The check cannot create or mutate candidate, release, production, rollback, or ledger state.

## Permanent ledger

Permanent ledger #30 remains open. M12.3 does not append to it because no governed production content batch is being approved or promoted.
