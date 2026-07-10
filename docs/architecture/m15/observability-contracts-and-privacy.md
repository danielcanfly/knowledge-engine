# M15.1 Observability Contracts and Privacy Policy

Parent: #204  
Slice: #205

## Baseline

- Engine: `0d77598a530b59d5bb6006da282b7728bb21a751`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`
- Permanent ledger: #30 remains open and unchanged.

## Purpose

M15.1 defines the vocabulary and safety envelope for later observability work. It emits no production telemetry, installs no vendor exporter, repairs no object, and acquires no Source or production write authority.

## Closed event-family registry

The v1 contract contains exactly these families:

1. `runtime_request`
2. `retrieval`
3. `citation`
4. `acl_filtering`
5. `release_activation`
6. `cache_identity`
7. `pointer_health`
8. `r2_object_health`
9. `batch_lifecycle`
10. `promotion_replay_rollback`
11. `feedback_triage`
12. `freshness_impact`
13. `alert_state`

Adding a family requires a schema-version change and review. Unknown families are not silently accepted.

## Identity and correlation

Every event carries:

- exact Engine commit SHA;
- canonical Source commit SHA;
- `request_id` or `operation_id`;
- exact release and manifest identity whenever a release is involved;
- pointer identity whenever pointer state is being asserted;
- timezone-aware UTC timestamp.

Correlation identifiers may be transformed before export. They must never be metric labels.

## Metric policy

Metric names begin with `knowledge_engine_`. Units are closed to `count`, `seconds`, `ratio`, and `bytes`.

Allowed dimensions are bounded enums or buckets:

- audience;
- status;
- transport;
- surface;
- error code;
- cache result;
- health state;
- lifecycle state;
- decision;
- severity;
- sample class;
- region class.

Request IDs, operation IDs, release IDs, concept IDs, source IDs, URLs, arbitrary user agents, exception text, and free-form strings are forbidden metric dimensions. Each metric declares an explicit `max_series` ceiling.

## Privacy policy

The following are forbidden by default and must be dropped before persistence or export:

- raw query and prompt text;
- raw answer text;
- bearer tokens, cookies, and JWTs or claims;
- raw IP address and client hostname;
- private source excerpts;
- private `s3://`, `r2://`, and `file://` locations;
- arbitrary headers or request bodies.

Permitted transformations are `drop`, `sha256`, `truncate`, and `bucket`. Hashing is not permission to collect forbidden content. Raw content remains forbidden even when a sink claims encryption.

## Retention

- `ephemeral_24h`: transient debugging aggregates that contain no forbidden fields;
- `operational_30d`: bounded runtime and health observations;
- `governance_1y`: deterministic decisions and lifecycle evidence with no raw user content.

Retention expiry is a deletion eligibility policy, not authority for physical deletion. M15.1 cannot delete production or evidence objects.

## Sampling and clocks

Sampling rates are explicit in `[0, 1]`. Sampling must not change answer, retrieval, ACL, citation, feedback, promotion, or rollback behavior. Security and governance failures must not be hidden by ordinary request sampling in later slices.

Timestamps are timezone-aware UTC. Maximum accepted clock-skew policy is 300 seconds. Later collectors must record clock-health failures rather than rewriting historical event time silently.

## Deterministic report identity

The acceptance report uses canonical UTF-8 JSON with sorted keys and compact separators, a final newline, and SHA-256 over the payload with `artifact_sha256` set to null. Re-running the same contract and baseline produces the same digest.

## No-write boundary

All of these remain false:

- Source write, package, or PR creation;
- candidate dispatch;
- production or pointer write;
- automatic pointer repair;
- rollback;
- physical deletion;
- automatic correction;
- permanent-ledger append.

M15.2-M15.7 may consume these contracts, but any new authority requires a separate reviewed contract. Telemetry failure must remain fail-open for answer execution and fail-closed for claims that observability evidence exists.

## Acceptance threats

Tests reject:

- secret-bearing fields and values;
- private object URIs;
- raw query, answer, IP, host, and excerpt fields;
- high-cardinality dimensions;
- non-UTC timestamps;
- release identity without manifest identity;
- event-family drift;
- digest mismatch;
- any attempted write authority.
