# M25.10 Blog Source Admission and Candidate Deployment

Status: `engine_extension_under_exact_head_review`

## Authority

Daniel authorised live Source admission and candidate-only deployment for the exact M25.9 Blog Batch A and Batch B baselines. Production pointer and public production traffic remain outside this authority.

## Exact source identities

- upstream repository: `huaihsuanbusiness/daniel-blog`
- upstream commit: `97821b6547ce3c0b8b8acf11cbbf4795684df458`
- master inventory: `ee8589e4e2ce19005507fc5b9f3aa47d3c0320ab34848e81948c5cdaad7f729e`
- Batch A inventory: `734b6d5d346ad1e283d8d420332e6dab0f6c77074f7a4ed445bbcba62144f879`
- Batch B inventory: `f58b1be75093ad4f530e5317c35055a9b1cc21d56cef6b921550fd544b976988`
- combined candidate nodes: `68f8040a790d55276ced5d19f67c022dc645d801dd2749c46739f91d9f031440`
- combined candidate edges: `21c5a739a1bf2bcd78bdb032e71afc8b89d68b9c4180f626742567f39233aed8`
- Source admission seal: `f5f01d82c7a1a38cf15fc54c890b904c4c015f608e2d25e294f9469f9b1927f2`

## Native Document Source Pack

The accepted corpus is admitted below `documents/daniel-blog-en-156/` in `knowledge-source`. It is not placed below `bundle/concepts/`, because a long-form article is a Source document, not automatically a canonical Concept.

The pack contains:

- 156 immutable English Markdown Sources;
- one complete master inventory and two exact batch inventories;
- 25 Series or collection nodes;
- 156 Article nodes;
- 4,041 H2/H3 Section nodes;
- 8,525 structural edges;
- Batch A and Batch B receipts;
- one signed live-admission record.

## Release augmentation

The M25.10 runtime first invokes the existing deterministic Source builder for the canonical Concept bundle. It then validates and adds the Document Source Pack atomically.

The unified candidate release contains:

- the existing Concept graph and lexical index;
- all 4,222 blog structural nodes and 8,525 blog structural edges;
- a 156-record Source viewer index;
- exact document provenance records;
- 4,197 retrieval documents, consisting of 156 Article overviews and 4,041 Sections;
- a BGE-M3 semantic-input artifact with fixed 1,024-dimensional model contract.

Every Article and Section retrieval document preserves the exact upstream repository, commit, path, content digest and source locator.

## Candidate semantic index

Live execution creates a release-specific, candidate-only Qdrant collection. It generates normalized BGE-M3 vectors through Cloudflare Workers AI, writes all 4,197 deterministic points, and requires full point-count readback before the candidate release is considered indexed.

Every payload binds:

- candidate release and channel;
- node and Source identity;
- Article and Series identity;
- canonical URL;
- source commit and path;
- line locator for Sections;
- content SHA-256;
- public audience;
- `production_authority=false`.

## R2 and runtime boundary

The augmented release is published to a `candidate-blog-*` channel. The production release pointer and public production traffic are not changed. The authenticated internal product may be rebound to this candidate identity after the candidate build, semantic readback and exact-source verification pass.
