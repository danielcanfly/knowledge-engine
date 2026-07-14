# M23.5 corrected benchmark contract and offline model selection

## Decision

The real Cloudflare Workers AI execution is accepted as immutable review evidence:

- evidence ZIP SHA-256: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`;
- model: `@cf/baai/bge-m3`;
- semantic artifact: `semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d`;
- document vectors: 107 rows, 1,024 dimensions, little-endian float32;
- query vectors: 16 rows, 1,024 dimensions, little-endian float32;
- Qdrant writes in the source evidence: false.

BGE-M3 is selected for a non-production pilot index. This is an embedding-provider
selection, not permission to change production retrieval or write the pilot collection.

`RETRIEVAL_MODE=lexical` remains authoritative.

## Why the benchmark contract needed correction

The inherited M20 suite evaluates exact section identifiers. The frozen M23.5 labels
point primarily to each article's `chunk-000`, even when the answer-bearing passage is
a later chunk. A retrieval can therefore route to the correct article and relevant
passage but still fail the exact-section metric.

M23.5 adds an overlay rather than weakening M20:

- existing `expected_section_ids` remain unchanged and produce a diagnostic;
- `expected_article_ids` are derived by removing the `/chunk-*` suffix;
- parent-article metrics are the provider-selection acceptance unit;
- exact-section metrics have no acceptance authority until passage labels are reviewed.

The overlay is pinned to benchmark suite SHA-256
`086cfb2648626dbe2cca64376dffaa6aea24e807c71f6b2b89e9ab1796d67f0e`.

## Calibration and held-out split

The 16 existing query vectors are reused. No Cloudflare call is required.

- calibration positives: `m23q-001` through `m23q-010`;
- calibration negative: `m23q-015`;
- held-out positives: `m23q-011` through `m23q-014`;
- held-out semantic negative: `m23q-016`.

The runtime ACL for `m23q-016` remains empty. Its semantic probe separately scores the
existing vector against public documents, preventing ACL enforcement from being
mistaken for semantic abstention quality.

Observed threshold evidence:

- threshold: `0.525111616299042`;
- calibration separation: `0.1376600025010008`;
- held-out separation: `0.023057235559322153`;
- held-out negative threshold clearance: `0.0014441215134249896`;
- held-out accuracy: `1.0`.

The held-out result is directionally positive but too narrow for production abstention.
Promotion requires at least three independent held-out semantic negatives, `0.02`
clearance and `0.05` held-out separation.

## Corrected parent-article metrics

| Method | Recall@3 | MRR | nDCG@3 | Cross-language Recall@3 | Not-found |
|---|---:|---:|---:|---:|---:|
| lexical | 0.452381 | 0.892857 | 0.590789 | 0.5000 | 0.5000 |
| BGE-M3 vector | 0.714286 | 0.964286 | 0.829664 | 0.9375 | 1.0000 |
| fixed RRF k=60 | 0.607143 | 1.000000 | 0.752058 | 0.6875 | 0.5000 |

Simple RRF is not selected because lexical noise reduces recall, cross-language
performance and not-found accuracy. The preferred future candidate is vector-first
with a separately governed fallback.

## Offline rerun

```bash
knowledge-m23-rebenchmark \
  --evidence-zip M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip \
  --gold pilot/m23/m23-5-corrected-gold.json \
  --expected-evidence-sha256 \
    1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272 \
  --output /Users/daniel/LLM-Wiki-Evidence/M23.5_Offline_Rebenchmark
```

The command verifies the ZIP and manifest, rejects authority-bearing evidence, validates
the overlay, reads the existing float32 vectors, calibrates and evaluates separate
partitions, and emits deterministic result, decision and receipt JSON. It performs zero
network, Cloudflare, Qdrant, R2 or Source operations.

## Qdrant named-vector correction

The actual collection uses named vector `default`. Points use:

```json
{"vector": {"default": [0.0]}}
```

Before an explicit write, the adapter performs a read-only preflight and requires green
status, named vector `default`, size `1024`, distance `Cosine`, no sparse vectors and an
empty collection for the first pilot write. A write still requires
`--allow-qdrant-write` and separate operator authorisation.

## Authority and closure

- embedding provider selected for non-production pilot: yes;
- BGE-M3 semantic artifact verified through M20: yes;
- simple RRF selected: no;
- production retrieval change: no;
- production abstention gate passed: no;
- Qdrant pilot write authorised: no;
- Source PR #19 merged: no;
- R2 or pointer mutation: no;
- Graph Neural Retrieval: forbidden.

M23.5 may close as an embedding-selection milestone. Production retrieval, independent
abstention acceptance and the first Qdrant ingestion remain later, separately authorised
work.
