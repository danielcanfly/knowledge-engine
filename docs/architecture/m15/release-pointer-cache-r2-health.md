# M15.3 Release, Pointer, Cache, and R2 Health

Parent: #204  
Slice: #209

## Baseline

- Engine: `33dac39094071e7f057b1f9cb8bb78c9ab9b8fc3`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Purpose

M15.3 evaluates production identity and object health without mutating any surface. It compares observed release, manifest, pointer, cache, and object inventory against an explicit expected baseline.

## Closed states

- `healthy`: every required identity and object check passed;
- `degraded`: non-authoritative defects such as stale cache, size drift, or malformed optional ETag;
- `unhealthy`: release, manifest, pointer, required-object, or digest integrity failure;
- `unknown`: the probe failed, so health must not be claimed;
- `not_applicable`: reserved for future checks that do not apply to a deployment.

## Determinism

Issue codes are closed and sorted by code, component, and bounded object ID. Reports use canonical sorted JSON with a final newline and SHA-256 digest. The same baseline and observations produce the same artifact identity.

## Privacy and cardinality

Reports contain bounded object IDs, not private `r2://`, `s3://`, or `file://` locations. Raw exception strings, credentials, headers, request bodies, query text, answer text, source excerpts, and user identifiers are prohibited.

## Failure posture

Probe errors produce `unknown` and `probe_failure`. They do not interrupt product serving, but they fail closed for any assertion that production is healthy.

## No-repair boundary

This slice cannot write or repair pointers, purge caches, copy/delete/write R2 objects, promote or roll back releases, modify Source, dispatch candidates, accept corrections, or append permanent ledger #30.
