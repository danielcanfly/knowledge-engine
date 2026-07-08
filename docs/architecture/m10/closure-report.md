# M10 Closure Report

Status: implementation complete; governance evidence recorded in parent issue #125
Parent issue: #125
Closure issue: #144
Permanent audit ledger: #30, which must remain open

## Scope delivered

M10 established an immutable raw-evidence intake plane independent of any single content repository. It reuses the existing object-store and release foundations rather than creating a parallel persistence system.

The original initial set contained 9 source capabilities. They are implemented through 8 runtime connector types because local file and Markdown intentionally share `local_file` acquisition and the `markdown/1.0.0` normalizer.

Implemented capabilities:

1. local file;
2. Markdown;
3. bounded HTTPS web URL;
4. bounded local PDF;
5. exact Git repository path;
6. Google Drive document export;
7. media-derived Markdown evidence bundle;
8. meeting transcript evidence bundle;
9. offline database metadata export.

Implemented runtime connector types:

1. `local_file`;
2. `web_url`;
3. `local_pdf`;
4. `git_repository_path`;
5. `google_drive_document`;
6. `media_derived_markdown`;
7. `meeting_transcript`;
8. `database_metadata_export`.

## Shared contracts reconciled

All connector implementations use the same core model:

- deterministic canonical JSON;
- stable source identity;
- content-addressed immutable raw objects;
- immutable `intake-snapshot/v1` envelopes;
- versioned normalized derivatives;
- sanitized connector-specific acquisition evidence;
- hash-chained state-transition events;
- write-once terminal result/rejection evidence;
- secret rejection before raw persistence;
- prompt-like content retained only as untrusted data;
- unresolved ACL/license quarantine;
- exact replay idempotency;
- raw deduplication without source-identity collapse;
- `intake/v1/` namespace isolation.

## Permission reconciliation

Connector code is prohibited from writing:

- canonical Source;
- GitHub review or governance decisions;
- workflows or release requests;
- candidate builds;
- permanent production ledger entries;
- `channels/production.json`.

The closure contract tests import every connector identity and scan connector source for production/governance mutation surfaces.

## Execution reconciliation

- `web_url` is the only connector performing bounded network acquisition inside the connector implementation.
- `local_pdf` uses a constrained parser subprocess.
- `git_repository_path` uses constrained local Git commands and forbids network acquisition.
- Drive credential ownership remains outside intake core behind a bounded transport interface.
- media, meeting, and database connectors consume offline evidence bundles and perform no external synchronization, inference, or database execution.

## Production invariants

M10 began from the completed M9 production baseline:

- production release: `20260708T040116Z-69a9f445699a`;
- production pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`;
- production manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`.

The dedicated closure workflow reads `channels/production.json` and the referenced release manifest, verifies both byte-for-byte hashes and pointer fields, and performs no write or delete operation. Any mismatch blocks closure.

## Historical compatibility

- historical M5 raw captures and keys are not rewritten;
- the M5 production ledger remains append-only and open;
- M10 does not create a production ledger entry because no production release or pointer mutation occurs;
- the canonical Source remains unchanged;
- isolated release-integration channels are temporary test objects and are deleted after rollback verification.

## Known non-blocking debt

The meeting connector reuses selected local filesystem guards from the media bundle, so some hardlink and mutation failures retain `MEDIA_BUNDLE_*` reason-code names. The failures remain typed, sanitized, deterministic, fail closed, and covered by tests. A future common-helper refactor should rename these shared failures to `LOCAL_BUNDLE_*` without changing behavior.

Scoped lint exceptions accumulated in connector files are explicit in `pyproject.toml`; global lint policy was not loosened. Consolidating large connector modules and removing scoped formatting exceptions is maintenance work, not a missing security or lifecycle contract.

## Closure gates

The merged closure commit represents the following completed conditions. Exact workflow run IDs and the merge SHA are recorded in parent issue #125:

- [x] CI quality gates and all tests pass;
- [x] reference vertical slice passes;
- [x] container build passes;
- [x] R2 canary passes;
- [x] isolated R2 release integration passes, rolls back, and cleans up;
- [x] read-only production pointer verification passes;
- [x] final review confirms no connector or production mutation surface was added;
- [x] closure PR is merged with expected-head protection;
- [x] exact merge SHA and run IDs are appended to #125;
- [x] closure issue #144 is closed completed;
- [x] parent #125 is closed completed;
- [x] permanent audit ledger #30 remains open.

This report is accepted into `main` only after those conditions are true; any failed final-head workflow blocks merge and leaves the governance issues open.
