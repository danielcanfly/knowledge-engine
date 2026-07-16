# M23.7-R3.3 Offline Payload-v2 Rebuild and Retrieval Evaluation

## Governance

R3.3 is issue `#487` under parent `#474`. It begins from the independently reconciled R3.2 merge `2511269cb46cefd24c15636480e9592cdfcf8964` and consumes the accepted repair contract `9ed7a5bea7ce85aed67bf6f263c8b06420e1c67bd7cac62f9368f0f48c29c33e`.

This workstream is an offline readiness gate before any candidate Qdrant reingestion. It is not the R3 live acceptance rerun.

## Frozen inputs

- Evidence ZIP: `M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip`
- Evidence SHA-256: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`
- Semantic artifact: `semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d`
- Documents and vectors: exactly 107
- Model: Cloudflare Workers AI `@cf/baai/bge-m3`
- Dimension: 1024, L2-normalized, no query prefix change

## Rebuild

The operator verifies the evidence ZIP and its internal receipt, benchmark suite, semantic metadata, vector bytes and row bindings. It then builds 107 deterministic candidate points with payload schema v2.

Each point binds the same document row to:

- deterministic point ID;
- `section_id`, `concept_id`, `section_title` and `language`;
- source and text hashes;
- exact normalized vector;
- a per-row binding digest;
- fail-closed non-production authority flags.

The full candidate artifact is written locally. Raw source text is not carried into the candidate point payload.

## Repaired evaluation

The bounded sample rule is reproduced offline: eligible points are ordered by deterministic point ID and the first eight are selected. The repaired compiler builds eight semantic queries from title, concept, structural locator and language.

All eight text-only query SHA-256 identities must be unique. The operator sends the eight synthetic query texts in one BGE-M3 batch, then performs a complete local cosine ranking against all 107 frozen document vectors.

The receipt persists only query hashes, target IDs, ranked IDs, target ranks, scores, metrics, hubness and bounded authority fields. Raw query text is used in memory and is not persisted.

## Readiness thresholds

R3.3 passes only when all identity and authority gates pass and:

- Recall@5 is at least `0.82`;
- MRR@10 is at least `0.68`;
- nDCG@10 is at least `0.72`.

Thresholds are unchanged from R3.

## Authority boundary

R3.3 authorizes one bounded Workers AI embedding batch and local computation only. It dispatches no Qdrant read, write, delete or reindex; no R2 or pointer mutation; no Source mutation; no deployment or serving; and no promotion decision.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` remains open.

## Exit

A passing R3.3 receipt authorizes only a separately governed candidate Qdrant reingestion proposal. Candidate reingestion and the subsequent R3 live acceptance rerun require their own issues, exact-head CI, reconciliation and explicit authority.
