# M16.4 R2 Object Loss and Release Restoration

M16.4 defines deterministic detection, planning, and verification evidence for release-object loss without adding a new production R2 executor.

## Exact baseline

- Engine: `872fe9989cf9302b59b81fae6009c7ebac8d4cac`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Damage detection

Every expected release object is identified by a bounded public object ID, size, SHA-256, and optional normalized ETag. Observations are classified as healthy, missing, size mismatch, digest mismatch, ETag mismatch, or probe failure.

Private bucket names, R2/S3/file URIs, credentials, raw queries, raw answers, private excerpts, IPs, hostnames, and arbitrary exception text are not accepted evidence fields.

## Trusted retained release

A retained release is eligible as a restoration source only when all of these are true:

- the release is immutable;
- its inventory is complete;
- its manifest is verified;
- its canonical Source identity is verified;
- the requested object exists;
- the retained object's size, SHA-256, and ETag match the expected production object.

An untrusted retained release never becomes a convenient substitute. The report blocks instead of copying uncertain bytes into a larger blast radius.

## Restoration states

For every damaged object, the evaluator produces one of four useful outcomes:

- `planned`: the trusted source is available but governed authorization or execution evidence is still absent;
- `verified`: authorized external execution is represented and the restored object matches exactly;
- `blocked`: identity, retained-source, or post-restore evidence failed;
- `unknown`: the observation cannot support a deterministic conclusion.

The contract does not invoke `put_object`, `copy_object`, `delete_object`, pointer mutation, cache purge, or rollback. It evaluates evidence from an isolated drill or an existing governed operation.

## Post-restore acceptance

A completed restoration is `restored_and_verified` only when all required gates pass:

- exact Engine, Source, release, manifest, and pointer identity;
- all damaged objects restored with exact size, SHA-256, and ETag;
- manifest reconciliation;
- production pointer remains byte-for-byte unchanged;
- cache refresh and runtime binding to the expected release;
- post-restore query success;
- citation verification;
- ACL-negative query remains denied;
- bounded evidence is complete;
- no write authority exists in this slice.

Missing authorization or execution evidence yields `ready_for_governed_restore`, not a false success. Any failed object or runtime gate yields `blocked`.

## Deterministic evidence

Object results and gates use stable sorting. Reports use canonical JSON and SHA-256 identity. Reordering equivalent inventories produces the same digest, while changing a finalized decision causes digest verification to fail.

## Authority boundary

M16.4 cannot:

- modify canonical Source or create a Source PR;
- mutate production or its pointer;
- purge caches;
- write, copy, or delete R2 objects;
- promote or roll back a release;
- rotate credentials;
- physically delete data;
- append to permanent ledger #30.

This slice is the recovery blueprint and checksum inspector, not the crane moving production objects.
