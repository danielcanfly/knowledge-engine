# M10 Immutable Intake Architecture

Status: implemented, pending final closure verification
Milestone: M10 — Immutable Intake and Source Connectors
Architecture baseline: `3a17593eb1b2cd549e84b9287679023350b4f5b1`
Implementation baseline: `a3d1e2f0c42b089ce6b2e7d8ccaefe2c750a53ad`
Production mutation: forbidden

This package defines and records the production intake plane that generalizes the M5.1 Markdown vertical slice without replacing its proven object-store primitives.

## Governing result

M10 now implements nine initial source capabilities through eight runtime connector types. Local file and Markdown are intentionally one connector type: `local_file` acquires exact local bytes and uses `markdown/1.0.0` as the Markdown normalizer. A second, duplicate `markdown` connector type was not created.

All connectors reuse the `intake/v1/` immutable raw, snapshot, derivative, event, result, rejection, replay, dedupe, ACL, license, and quarantine contracts. No connector may write canonical Source, governance decisions, release requests, candidates, permanent production ledger entries, or production channels.

## Documents

1. `ADR-001-immutable-intake-plane.md`
2. `connector-protocol-v1.md`
3. `intake-state-machine.md`
4. `r2-key-layout.md`
5. `acl-and-audience-invariants.md`
6. `threat-model.md`
7. `test-strategy-and-acceptance.md`
8. `m5-to-m10-migration-map.md`
9. `connector-inventory-v1.json`
10. `connector-matrix.md`
11. `operator-runbook.md`
12. `closure-report.md`
13. `../../../schemas/intake-snapshot-v1.schema.json`
14. `examples/snapshot-v1.example.json`

## Implemented connector types

- `local_file`
- `web_url`
- `local_pdf`
- `git_repository_path`
- `google_drive_document`
- `media_derived_markdown`
- `meeting_transcript`
- `database_metadata_export`

The machine-readable source of truth is `connector-inventory-v1.json`.

## Closure boundary

M10 closure requires all of the following at one reviewed head:

- CI and all contract tests pass;
- the existing reference vertical slice passes;
- the container builds;
- R2 canary passes;
- isolated R2 release integration passes and rolls back;
- read-only production verification proves the M9 production pointer and manifest remain byte-for-byte unchanged;
- issue #125 receives final evidence and is closed completed;
- permanent audit ledger issue #30 remains open and unchanged.

Until those checks pass, the status above remains “pending final closure verification.”
