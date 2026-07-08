# M10 Operator Runbook

This runbook governs verification and operation of the immutable intake plane. It does not authorize production mutation.

## 1. Select the connector

Use `connector-inventory-v1.json` as the source of truth. Confirm the exact connector type, connector version, normalizer/parser identity, maximum input limits, network/subprocess boundary, and special evidence schema before acquisition.

Markdown is acquired through `local_file`; there is no separate runtime `markdown` connector type.

## 2. Prepare source facts

Every request must provide or explicitly mark unresolved:

- owner evidence;
- license evidence;
- audience;
- access policy and principals;
- retrieval timestamp in strict UTC;
- source version or immutable revision where the connector requires one;
- parent snapshot when the request represents a known successor.

Never replace unresolved ACL or license evidence with public defaults.

## 3. Run intake in a non-production output workspace

The connector may write only the `intake/v1/` evidence namespace through the configured `ObjectStore`. Local output directories are optional diagnostic mirrors, not canonical evidence.

Before accepting a result, inspect:

- terminal status;
- source, snapshot, and derivative IDs;
- raw key and raw-reuse result;
- connector-specific evidence key;
- ordered event keys;
- warnings;
- rejection or quarantine reason when present.

## 4. Interpret terminal states

- `accepted_for_compilation`: all source safety, ACL, ownership, and license gates passed;
- rejection before snapshot: source bytes were not durably persisted;
- quarantine after snapshot: immutable evidence exists, but unresolved ACL/license or another admission condition blocks compilation;
- exact replay: immutable objects are reused and the result becomes idempotent;
- collision or integrity failure: stop and investigate, never overwrite the existing key.

## 5. Connector-specific checks

### Web

Confirm final HTTPS URI, redirect chain, validated and connected IPs, MIME observation, compression accounting, retries, and safe response headers. Signed URLs and credential-bearing query parameters are forbidden.

### PDF

Confirm parser identity, page/object/stream limits, active-content checks, subprocess isolation, and absence of encryption, OCR, repair, attachments, and JavaScript execution.

### Git

Confirm the repository is local, the commit is a full immutable SHA, the path resolves to one tracked regular file, and no clone/fetch/pull/submodule update occurred.

### Drive

Confirm the exact expected current revision, export MIME, shared-drive behavior, pre/post metadata stability, permission digest stability, and non-broadening principal proof. Credential ownership remains outside intake core.

### Media

Confirm exact media/transcript/manifest hashes, supported media signature, duration, time-aligned segments, derivation tool/model identity, and that no decoder or transcription model ran inside intake.

### Meeting

Treat speaker labels as aliases, not human identities. Confirm participant verification state, ACL principal proof, meeting UTC windows, segment references for every agenda/decision/action annotation, and no model inference.

### Database metadata

Confirm the export is offline and contains schema metadata only. Rows, samples, counts derived from data, SQL/DDL bodies, connection details, credentials, and executable queries are forbidden. Validate FK, view dependency, grant, index, and RLS references.

## 6. Required verification before an M10 code merge

At one exact PR head require:

1. CI quality gates and the full test suite;
2. existing reference vertical slice;
3. container build;
4. R2 canary write/read/delete;
5. isolated R2 release integration with promotion, query, ACL, rollback, and cleanup;
6. final diff review against connector permission boundaries.

For milestone closure also require the dedicated read-only production check:

```bash
python scripts/m10_verify_production_baseline.py --confirm-read-only
```

The command is intentionally read-only. It calls `get` for `channels/production.json` and its referenced manifest, then verifies exact SHA-256 values. It must never call `put`, `delete`, publish, promote, rollback, or create a candidate.

## 7. Production baseline expected at M10 closure

- pointer key: `channels/production.json`
- pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`
- release ID: `20260708T040116Z-69a9f445699a`
- manifest key: `releases/20260708T040116Z-69a9f445699a/manifest.json`
- manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`

Any mismatch blocks closure. Do not “repair” production as part of M10 closure.

## 8. Governance closure

After all workflows pass at the reviewed head:

- merge with expected-head protection;
- append exact SHAs and run IDs to issue #125;
- close the closure child issue completed;
- close #125 completed only after the final evidence comment exists;
- verify permanent audit ledger #30 remains open;
- do not append a production ledger entry because M10 made no production release.
