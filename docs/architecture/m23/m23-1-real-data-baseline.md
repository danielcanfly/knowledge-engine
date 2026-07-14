# M23.1 Real-Data Baseline and Pilot Corpus

Status: implementation for issue #365

Production mutation dispatched: false.

## Exact entry baseline

- Engine: `14a7f9bcf375925458e17272418d6db9aa308caf`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`

These identities were reverified against live GitHub state before the branch was opened.

## Source-authority decision

The user supplied six Markdown files representing three bilingual Harness Theory articles. Live repository discovery across the GitHub App installation found no connected Blog repository containing these exact files, and repository-wide searches found no matching Harness Theory commits.

M23.1 therefore records the conversation uploads as the source authority. It locks exact upload IDs, filenames, SHA-256 digests, byte and line counts, frontmatter identities, language, part, and counterpart mapping. Repository, commit, path, blob, and canonical URL fields remain explicitly `null`; the implementation rejects any attempt to fill them without evidence.

This is an intentional truth-preserving variance from the repository-backed route described in the handoff. It is safer than inventing a repository identity. M23.2 owns article-byte intake and may replace unresolved location fields only when an exact authoritative source is available.

## Pilot corpus

The corpus contains three logical articles and six documents:

| Logical article | zh-TW SHA-256 | English SHA-256 |
|---|---|---|
| Harness Theory Part 01 | `c1deaf4fce0673f9c92c9b4e0b5c1ad994964f7cb6e83a10c76d807ac7a3f86b` | `9b988a0e38a3142d94a72ff0d85e9b58ba1a9b5a294ad7f9a88a60832d9e39e8` |
| Harness Theory Part 02 | `4f5d265e2a4ff81d3744b3a72bd09cb2b1c2682f144fb9be90c38babeb6b0da7` | `baa1ea6c5dc251759c42972a42a53a22c7368851d88d48122b49047b79377908` |
| Harness Theory Part 03 | `ab637ca15ab867ce169cbc4062bd8e455842627648511c7fb2f294092155f7d1` | `a6df919cc2f03a1351d20c2c8bbe97044698eea39fc0703f11ef061545c97172` |

The machine-readable inventory is `pilot/m23/m23-1-corpus-manifest.json`. Its digest is `ad63e9fa78780b1c8774a66fe6d3d1d20b3fd52b62adc559d80cc9ac4fa38cae`.

All source files reference local image paths, but no image files were supplied. The manifest records every path and requires `image_assets_supplied: false`; captions and Markdown references are evidence, while the absent image bytes are not.

## Frozen golden queries

`pilot/m23/m23-1-golden-queries.json` contains 16 immutable queries and is bound to the corpus manifest digest. It was defined before selecting an embedding model, provider, prompt, retrieval weight, or evaluation threshold.

Coverage includes:

- exact titles in Chinese and English;
- paraphrases;
- Chinese questions for English technical concepts;
- English questions for Chinese explanations;
- comparisons across parts;
- dependency and authority questions;
- one unrelated not-found question;
- one ACL-negative request that must be denied.

The golden-query digest is `3cdfa98add7b1418f7582fbcb6e7e4f6475c5a06dc0c7e305a6044c970e31fac`.

## Deterministic validation

`validate_real_data_baseline` requires:

- the exact Engine, Source, and Foundation entry identities;
- six unique upload IDs and six unique content digests;
- exactly three reciprocal Chinese/English pairs;
- explicit unresolved repository and URL fields;
- no fabricated repository identity;
- at least twelve queries covering every required query class;
- corpus-to-query digest binding;
- complete protected-state declarations with every mutation set to false.

## Scope exclusions

M23.1 performs no article-byte ingestion, normalization, Source write, R2 write, production-pointer update, provider/model call, extraction, embedding generation, traffic change, multi-hop activation, or Graph Neural Retrieval.

M23.2 may begin only after this issue has an expected-head implementation merge and separate reconciliation.
