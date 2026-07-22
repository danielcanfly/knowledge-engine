# M25 Adapter Boundaries

The machine-readable adapter map is `pilot/m25/m25-1-adapter-boundaries.json`.

## Intake adapter

Reads existing `intake/v1` snapshots and derivatives. It writes only `admission/v1` plans and
states. It cannot rewrite raw bytes or derivatives.

## Batch adapter

Reuses the M21.2 plan/checkpoint transition rules and binds them to an M25 admission plan. It does
not create a scheduler, queue, or unbounded retry loop.

## Identity adapter

M21.5 is not directly reusable because it pins Source SHA `a6ba738d910d01d2ae99b1968f0831989934c549`. The M25
adapter must receive a verified Source snapshot at `acf78596ace8a7366688ccef72b507204d09d9f9`, preserve the outcome taxonomy,
and emit benchmark-compatible evidence. It may not modify Source.

## Review and Source PR adapter

Reuses M11/M21 packets and complete Daniel decisions. M25.7 may prepare and open a bounded Source
PR only after digest, completeness, collision, and stale-head checks. Opening a PR does not grant
merge authority.

## Hidden I/O rule

Adapters must declare every read and write surface. Hidden network calls, hidden filesystem reads,
implicit environment credentials, and cross-release fallback are forbidden.
