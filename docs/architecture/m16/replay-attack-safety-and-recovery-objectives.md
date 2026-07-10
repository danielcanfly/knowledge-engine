# M16.6 Replay-Attack Safety and Recovery Objectives

M16.6 defines deterministic replay-safety and recovery-objective evidence without adding a promotion, rollback, pointer, cache, R2, Source, or ledger mutation executor.

## Exact baseline

- Engine: `139ec0cdd79ca2644a57ebe3a60e2c42c9aa0d9d`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Every observation and report carries the complete identity tuple. Identity drift blocks compliance.

## Replay safety

Every operation attempt carries:

- a unique attempt ID;
- an operation ID;
- a monotonically increasing sequence;
- a closed operation kind;
- a payload SHA-256;
- the exact expected-previous pointer SHA-256;
- an optional resulting pointer SHA-256;
- a terminal state;
- a bounded mutation claim;
- privacy-safe evidence codes.

The evaluator rejects:

- stale expected-previous pointers;
- operation IDs reused with different payloads;
- resurrection of an operation already recorded as rolled back;
- a second mutation claim for the same operation;
- duplicate or out-of-order sequence claims;
- missing or mismatched resulting-pointer evidence;
- final pointer identity that cannot be derived from the accepted sequence.

An exact duplicate request is idempotent only when its operation kind, payload digest, expected-previous pointer, resulting pointer, and prior terminal result all match and the replay does not claim a second mutation.

A new operation after rollback is valid only when it has a new operation ID, a later sequence, and the exact pointer that is current after rollback.

## Recovery objectives

The closed policy defines bounded thresholds for:

- recovery time objective, measured from detection to service restoration;
- recovery point objective, measured as lost durable events;
- maximum release unavailability;
- maximum rollback duration;
- maximum evidence-recovery duration.

All timing comes from explicit timezone-aware UTC timestamps. Missing evidence becomes `unknown`; threshold breaches become `failed`; rollback time is `not_applicable` when no rollback occurred. Negative or non-monotonic timelines are rejected.

## Decisions

- `compliant`: replay gates pass and every required recovery objective passes or is not applicable;
- `non_compliant`: a replay or identity gate is blocked, or an objective is exceeded;
- `unknown`: required timing, RPO, or evidence data is missing.

The report includes stable attempt, objective, and gate ordering, canonical JSON, SHA-256 identity, and tamper detection.

## Evidence safety

Evidence rejects raw queries, raw answers, credentials, bearer/JWT/cookie material, private excerpts, IP or hostname data, repository/object URIs, arbitrary exceptions, and unknown extra fields. Collections and identifiers are bounded.

## Authority boundary

M16.6 cannot:

- promote or roll back a release;
- mutate or repair the production pointer;
- purge runtime caches;
- write, copy, or delete R2 objects;
- write canonical Source or create a Source PR;
- rotate credentials;
- physically delete data;
- append to permanent ledger #30.

It is the turnstile and stopwatch for recovery operations, not the machinery that moves production state.
