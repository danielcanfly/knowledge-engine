# M12.3 Governance Boundary

M12.3 is a Runtime evaluation-governance slice. It adds a quality baseline check over golden query reports and deliberately stops before any Source, release, production, rollback, or ledger mutation.

## Allowed

- Read a deterministic golden query suite report.
- Read an immutable baseline contract.
- Compare aggregate quality, identity, release, manifest, required cases, allowed failure reasons, and audiences.
- Emit deterministic evaluation evidence.
- Mark evaluation failures as release-blocking.

## Denied

- Canonical Source writes.
- Source PR creation.
- Candidate creation.
- Release creation.
- Production pointer updates.
- Rollbacks.
- Permanent ledger appends.
- Audience broadening.
- Silent baseline mutation.

## Downstream use

A downstream release workflow may consume `gqbaselinecheck_` artifacts as a gate. This slice does not wire the gate into promotion or production. That separation keeps M12.3 replayable and non-mutating while preserving a clear release-blocking decision surface for later M12 stages.
