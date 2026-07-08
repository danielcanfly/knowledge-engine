# M10 Connector Matrix

The authoritative machine-readable inventory is `connector-inventory-v1.json`. This document explains the operational differences.

| Capability | Runtime connector type | Version | Normalizer or parser | Special evidence | Network | Subprocess |
|---|---|---|---|---|---:|---:|
| Local file | `local_file` | `local-file/1.0.0` | `markdown/1.0.0` | shared M10 evidence | no | no |
| Markdown | `local_file` | `local-file/1.0.0` | `markdown/1.0.0` | shared M10 evidence | no | no |
| HTTPS web URL | `web_url` | `bounded-https/1.0.0` | MIME-selected v1 normalizer | `web-acquisition/v1` | bounded HTTPS only | no |
| PDF | `local_pdf` | `local-pdf/1.0.0` | `pypdf_text/6.14.2` | `pdf-parse-evidence/v1` | no | isolated parser |
| Git repository path | `git_repository_path` | `git-path/1.0.0` | Git Markdown/text v1 | `git-acquisition-evidence/v1` | no | bounded local Git |
| Google Drive document | `google_drive_document` | `google-drive-document/1.0.0` | Google Docs text v1 | `drive-acquisition-evidence/v1` | external transport boundary | no intake subprocess |
| Media-derived Markdown | `media_derived_markdown` | `media-derived-markdown/1.0.0` | media transcript v1 | `media-acquisition-evidence/v1` | no | no |
| Meeting transcript | `meeting_transcript` | `meeting-transcript/1.0.0` | meeting transcript v1 | `meeting-acquisition-evidence/v1` | no | no |
| Database metadata export | `database_metadata_export` | `database-metadata-export/1.0.0` | database metadata v1 | `database-acquisition-evidence/v1` | no | no |

## Shared invariants

Every connector must preserve these boundaries:

1. raw bytes are content-addressed and immutable;
2. snapshot identity binds source facts, ownership, license, audience, ACL, version, and raw content identity;
3. normalized output is a rebuildable, versioned derivative;
4. secret-like content is rejected before raw persistence;
5. prompt-like instructions remain untrusted source data;
6. unresolved ACL or license never silently becomes public;
7. exact replay is idempotent;
8. equal raw bytes may deduplicate without merging distinct sources or snapshots;
9. event evidence is append-only and hash chained;
10. connector code cannot write canonical Source, governance decisions, candidates, release requests, the permanent production ledger, or production channels.

## Execution boundaries

The web connector is the only connector that performs network acquisition inside the connector implementation. It is HTTPS-only and includes destination, redirect, DNS, TLS, retry, compressed-byte, decompressed-byte, and truncation controls.

The PDF and Git connectors use bounded subprocesses. PDF parsing is isolated and cannot use network, OCR, JavaScript, attachments, or password handling. Git reads committed local objects at an exact full commit and cannot clone, fetch, pull, or update submodules.

The Drive intake core owns no credentials. Authentication and token handling remain in an external transport implementing the bounded Drive protocol.

Media, meeting, and database connectors ingest offline evidence bundles. They do not download media, transcribe speech, infer speakers, synchronize meeting platforms, connect to databases, execute SQL, or run models.

## Reconciled capability count

The original architecture listed nine source forms and also showed both `local_file` and `markdown` in the conceptual type list. The implementation intentionally delivers Markdown through the `local_file` connector rather than creating two path-reading connectors with overlapping authority. The final count is therefore nine source capabilities and eight runtime connector types.

## Known non-blocking debt

The meeting bundle currently reuses selected local filesystem guards from the media bundle. Some hardlink and mutation failures retain `MEDIA_BUNDLE_*` reason-code names. The behavior is fail closed and covered by tests; the naming should become connector-neutral `LOCAL_BUNDLE_*` during a later common-helper refactor. It does not broaden permissions, lose evidence, or alter admission behavior.
