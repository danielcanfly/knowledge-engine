# M26.PA.2 Real-Corpus Retrieval Binding

Issue: `#1186`  
Fresh branch base: `728df7da4e6b9320c25abb904a65a32b15e62bb1`  
Unified M26 v3 SHA-256: `6e71ca5981e3eb45987d188c9c7fb2851a4b5f31803655dd2fc7e28ed4bd22a9`  
PA.2 stage package SHA-256: `f9529b30d9b33943d6bc658f8d60b97b35acf76de2c42c46c46b1e52cdc67a69`

## Current status

This change is the fresh-branch, non-live P0/P1 repair required after accepted G0 and
PA.1 reconciliation. It is intentionally non-accepting:

- `accepted = false`
- `live_execution = false`
- no real R2 or Qdrant request is made by this PR
- no secret is read or persisted
- no provider or answer-generation path is invoked
- no Source, Foundation, release, pointer, R2, Qdrant, Worker, Pages, DNS, Access, or
  traffic surface is mutated

A code-only merge does not accept PA.2. A later exact read-only live run requires Daniel's
separate approval of the exact head, environment, attempt, credential scope, and read
surface. Live evidence and an independent PA.2 reconciliation remain mandatory.

## Accepted predecessors

- G0: `m26_g0_milestone_reconciliation_accepted`
- PA.1: `m26_pa_1_production_activation_authority_freeze_accepted`
- G0 reconciliation seal: `728df7da4e6b9320c25abb904a65a32b15e62bb1`
- M25: `m25_closed`
- M25 closure implementation merge: `dd373e932b75c89de3bdea45e581fd0df512c40b`

The legacy branch `chatgpt/m26-12-real-corpus-binding` at
`40061ebf66b057dca490708b7abbaa5988b4edb8` remains candidate-only provenance. It is not
merged, rebased, or run live.

## Frozen production identity

- pointer: `channels/production.json`
- pointer SHA-256: `4a2cf8cc16d598cc2c6928491cf2c3b926e57e571297c61a8c3ff7a4ae396ff9`
- release: `m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043`
- production manifest:
  `releases/m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043/promotion/m25-10-production-manifest.json`
- production manifest SHA-256:
  `72bb03e3fa22e453735719ab43898adfd4c7f186f818ed71685efb4fcd87de2b`
- Qdrant collection:
  `m25_blog_m25blog_5250f8422f4f_f5f01d82c7a1_fe499db2e043_fe499db2e043`
- filtered population: `4197`

The production pointer authorises the immutable M25 candidate collection without rewriting
its points. The exact Qdrant filter therefore retains `candidate_release_eligible=true` and
`production_authority=false`, together with the frozen release, Source, and admission
identities.

## P0 repair

### Strict contracts

The entry contract, retrieval policy, contract registry, receipt schema, and failure schema
are Draft 2020-12 contracts. Unknown fields are rejected. Every contract carries a
self-digest, the registry binds child object digests and raw schema byte digests, and the
accepted G0/PA.1/M25 predecessor identities are revalidated.

### Read-only proof

The runtime accepts capability-bounded interfaces only:

- R2: `get`
- Qdrant: `count`, `scroll`

The adapter surface is rejected if it exposes a callable mutation method, presents a
non-read-only scope, or does not match the frozen credential contract digest. Only the
names of the future read-scoped secrets are recorded. Values are never read by this PR.

### Payload confinement

Qdrant is called with an explicit nine-field payload selector and `with_vector=false`.
Every returned key and value is recursively scanned. Unknown fields, nested material,
raw-text-like keys, secret-like keys or values, credential-bearing URLs, excessive strings,
and vectors fail closed. Receipts retain only identifiers converted to SHA-256 plus the
already-existing `text_sha256` metadata.

### Pointer, manifest, and inventory

The pointer and manifest bytes are checked against their frozen SHA-256 values before
parsing. The runtime then validates channel, release, manifest key, authority, engine,
Source, Foundation, admission, all seven population counts, every artifact entry, required
artifact kinds, path confinement, uniqueness, byte counts, media metadata, and digests.

## P1 repair

The runtime performs an exact filtered count, traverses the complete 4,197-point population
in bounded pages, rejects repeated offsets and partial pages, detects duplicate point and
section IDs, and derives the five-item sample by a stable canonical hash rank over frozen
metadata and sample seed.

HTTP handling is bounded to zero or one retry. It fails closed on timeout, rate limiting,
4xx, retry-exhausted 5xx, malformed JSON, and non-`ok` Qdrant envelopes. Success and failure
receipts are deterministic, strict, self-digested, metadata-only, and record exact operation
and non-mutation counts.

## Verification

The focused suite contains 126 contract, security, authority, transport, pagination,
identity, determinism, and evidence tests. It includes digest-preserving structural attacks,
so validation cannot pass merely because a modified object was rehashed.

The PR workflow also reruns G0, PA.1/M26.11, and M25 closure/reconciliation regressions,
builds non-live evidence twice and compares the bytes, enforces the exact eleven-file
surface, scans for secret values, and uploads only the non-live contract evidence.
