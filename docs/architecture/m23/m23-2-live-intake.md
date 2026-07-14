# M23.2 Live Intake and Injection

Status: implementation for issue #368

Production mutation dispatched: false.

## Exact entry baseline

- Engine: `3e69058e94b3ba039601e64895d3d17265391750`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.1 corpus manifest: `ad63e9fa78780b1c8774a66fe6d3d1d20b3fd52b62adc559d80cc9ac4fa38cae`
- M23.1 golden queries: `3cdfa98add7b1418f7582fbcb6e7e4f6475c5a06dc0c7e305a6044c970e31fac`

## Source authority

The six M23.1 conversation uploads remain the authoritative article bytes. No repository,
commit, blob, path, or canonical URL is invented. The live executor reads each original
filename from an explicitly supplied source root and verifies its exact byte count and SHA-256
before any object is written.

## Execution model

`execute_live_intake` connects the M23.1 corpus contract to the existing `intake_markdown`
and `FileObjectStore` implementation. One invocation creates:

- a stable batch plan bound to the exact corpus manifest and release identities;
- a digest-protected mutable checkpoint with typed per-item states;
- immutable raw content-addressed blobs;
- immutable capture metadata and normalized Markdown;
- review-required packets with canonical write disabled;
- immutable per-item result records;
- a final metadata-only execution receipt.

A failed item receives one attempt in the current invocation. It is not retried automatically.
The operator must explicitly pass `--retry-failed`; attempts are bounded to two. A partial
receipt may advance to the final receipt for the same batch, but a completed final receipt is
immutable.

## Real pilot execution

The six supplied articles were executed against a filesystem evidence store with the fixed
retrieval timestamp `2026-07-14T09:15:00Z`.

- batch ID: `m23batch_d7a9c85f4ac8070448ccf7d96037d320`
- item count: 6
- completed: 6
- failed: 0
- receipt SHA-256: `480b51aca822a2a28f36692edbb677eade77c93e2c85bf46def405878af3eae5`
- replay result: byte-identical receipt and unchanged capture identities
- evidence ZIP SHA-256: `8c12f57bde1a86dadbb2c4719ecedfd713427c8033dad4bab4369a1019ab03a4`

The repository stores only the metadata receipt. Raw article bytes, normalized derivatives,
object metadata, and review packets remain in the bounded pilot filesystem evidence package;
they are not added to Git history or R2.

## HTTPS fallback boundary

The primary M23.2 route is the pinned upload source root. The module also validates a bounded
caller-supplied HTTPS capture for future fallback use:

- HTTPS only;
- exact host allowlist;
- no URL credentials;
- no localhost, private, loopback, link-local, or reserved IP literal;
- port 443 only;
- at most three redirects, with every hop revalidated;
- `text/markdown`, `text/x-markdown`, or `text/plain` only;
- non-empty body capped at 2 MiB by default;
- final URL and complete redirect chain recorded;
- credentials sent is always false.

The validator does not grant network authority by itself. A later caller remains responsible
for applying the same checks before and after every actual network request.

## Recovery and replay

Checkpoint state is bound to the exact plan and batch. A previous `running` state is converted
to an explicit interrupted failure on resume. Completed items are not recaptured; their result
records, raw objects, and normalized objects are rehashed before reuse. Checkpoint tampering,
source drift, object collision, receipt drift, path traversal, and exhausted attempts fail closed.

## Scope exclusions

M23.2 performs no AI extraction, provider/model call, entity or relationship proposal, Source
write, R2 write, embedding generation, candidate or production publication, production pointer
update, traffic change, multi-hop activation, Graph Explorer deployment, or Graph Neural
Retrieval.

## Closure reconciliation

M23.2 was reconciled against live GitHub and filesystem evidence.

- authoritative issue: #368;
- implementation PR: #369;
- exact entry base: `3e69058e94b3ba039601e64895d3d17265391750`;
- accepted implementation head: `8fc19d76681e38604f85b7afc39f34fa3686299c`;
- expected-head implementation merge: `b77f4e32155056f3c9c1b661e745bf9966adcbe4`;
- implementation branch: `agent/m23-2-live-intake`;
- reconciliation branch: `docs/m23-2-live-intake-reconciliation`.

The accepted implementation diff contains exactly seven files:

- `.github/workflows/m23-2-live-intake.yml`;
- `docs/architecture/m23/m23-2-live-intake.md`;
- `pilot/m23/m23-2-live-intake-receipt.json`;
- `pyproject.toml`;
- `src/knowledge_engine/m23_live_intake.py`;
- `src/knowledge_engine/m23_live_intake_cli.py`;
- `tests/test_m23_2_live_intake.py`.

The accepted head passed M23.2 Live Intake #1, CI #750, M17 Architecture Canon Acceptance
#108, M18 Graph v2 acceptance #186, R2 Release Integration #503, R2 Canary #233, and every
M16/M17 workflow triggered by the CLI entry-point change. PR #369 had no conversation comments,
submitted reviews, or unresolved review threads.

Local prevalidation completed ten focused tests and compile checks. It found one genuine recovery
bug before PR creation: a partial receipt was incorrectly treated as an immutable final receipt.
The repair permits only a same-batch partial-to-final transition; a completed receipt remains
immutable. The real six-document batch completed with zero failures and replayed without identity
drift.

Source and Foundation remained unchanged. No R2 retention, Source write, production pointer,
provider/model call, extraction, embedding, publication, traffic change, multi-hop activation,
Graph Explorer deployment, or Graph Neural Retrieval occurred.

Production mutation dispatched: false.
