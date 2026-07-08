# M5.1 to M10 Migration and Reuse Map

## Reuse unchanged or with narrow extension

| M5.1 capability | M10 disposition |
|---|---|
| `ObjectStore` protocol | reuse |
| `FileObjectStore` | reuse for tests/local development |
| `R2ObjectStore` | reuse; preserve conditional writes |
| SHA-256 helper | reuse |
| immutable put pattern | extract/reuse as shared primitive |
| content-addressed raw key principle | retain under versioned namespace |
| UTF-8 Markdown normalization behavior | retain as Markdown normalizer v1 |
| secret and prompt-injection findings | retain as policy inputs; separate hard rejection from review findings |
| review packet write denial | retain downstream of compilation admission |

## Refactor

| Current coupling | M10 target |
|---|---|
| `IntakeRequest` mixes connector and policy facts | source descriptor + acquisition observation + snapshot envelope |
| `intake_markdown` reads local path directly | connector supplies bounded stream |
| capture identity includes normalized hash | snapshot identity binds raw evidence; derivative has separate identity |
| normalization occurs before durable snapshot | safety gate, raw snapshot, then versioned normalization |
| review packet built during intake | review packet generated downstream from accepted derivative |
| source kinds hard-coded to three text variants | connector registry and declared capabilities |
| capture status only `captured`/`review_required` | explicit attempt state machine |
| rejected secret content leaves no durable evidence | sanitized metadata-only rejection evidence |
| capture key namespace unversioned | `intake/v1/` namespace |

## Compatibility rules

- Do not rename or rewrite existing M5 R2 objects.
- Do not recompute historical capture IDs.
- A compatibility reader may map:

```text
legacy capture_id -> legacy_snapshot_id
raw_sha256 -> content_hash
raw_blob_key -> storage_location.key
normalized_sha256/key -> derivative record
request.kind -> connector/source kind
```

- Historical captures remain valid evidence for their original workflows.
- New connectors must use M10 contracts only.
- No mixed write path may write both legacy and M10 keys unless a later migration plan explicitly authorizes it.

## Known M5.1 gaps closed by M10

1. no connector abstraction;
2. no connector version/canonical locator contract;
3. no parent snapshot/source version model;
4. no structured access policy or unresolved ACL state;
5. no derivative tool/version identity;
6. no append-only attempt event chain;
7. no general rejection evidence;
8. no source-head/index rebuilding contract;
9. no binary/PDF/network safety model;
10. review generation coupled to acquisition.

## M10.2 implementation order

1. introduce schema models and canonical identity functions;
2. extract immutable-put helper without behavior regression;
3. add event/rejection writers;
4. add local-file connector and Markdown normalizer adapter;
5. add legacy M5 compatibility tests;
6. prove filesystem store;
7. prove isolated R2 candidate namespace;
8. inspect artifacts;
9. only then consider the next connector.
