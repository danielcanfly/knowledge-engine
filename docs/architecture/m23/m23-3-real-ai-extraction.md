# M23.3 Real AI Extraction Adapter

Status: implementation for issue #371

Production mutation dispatched: false.

## Exact entry baseline

- Engine: `c9a91bfbe21ee107b80cd79644cb398c9abbed95`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.2 batch: `m23batch_d7a9c85f4ac8070448ccf7d96037d320`
- M23.2 receipt: `480b51aca822a2a28f36692edbb677eade77c93e2c85bf46def405878af3eae5`

## Provider boundary

The pilot proposals were produced by the current ChatGPT session using GPT-5.5 Thinking.
The repository records this honestly as `openai-chatgpt-session`; it does not claim an API call,
API request ID, credential, billing event, or hidden provider transport that did not occur.

The adapter itself is provider-neutral. A request envelope freezes provider, model, model version,
prompt version, adapter version, seed, temperature, six normalized derivative identities, and the
requested output classes. A response envelope binds to that exact request and carries only strict
JSON proposals and candidate mappings.

## Real extraction result

The six M23.2 normalized Harness Theory documents produced:

- 38 total extraction proposals;
- 15 concept candidates;
- 12 untyped relation hints;
- 6 bilingual term candidates covering all three article pairs;
- 3 claim candidates;
- 1 alias candidate;
- 1 standalone definition candidate;
- 12 governed typed-relationship candidates;
- 34 governed tag candidates.

Exact identities:

- provider request: `172fc34e5dc744216b520db2ef3c58a111bea54590e8274f4443ec6e670873df`
- provider response: `32033c80219b2ab0b9013196253f546eac137c508b304e469b64f70eceb73fe3`
- extraction packet: `32f29be6fa4a90d6495b0844fbe0e8a2003dec25d3adf5328a0fd0b2232ce402`
- governed packet: `bc4a3c366d84baebd93982a39831fa7766e43a38018b0e0680e5b1c9f33c4875`
- execution receipt: `d12b3fec93ee0197852bd4db39d7c50842893a641cf576836bdd895a05c6d223`

Every proposal contains exact normalized-source character offsets and an excerpt SHA-256. The
provider response contains no article body. Full normalized text and generated packets remain in
the bounded operator evidence package outside Git history.

## Existing validator reuse

`execute_real_ai_extraction` converts the exact M23.2 completed batch into the established M21.2
plan/checkpoint contract without changing source identities. It then calls:

1. `m21_extraction_candidates.build_candidate_packet` for evidence spans, candidate IDs, bounded
   fields, controlled tags, authority rejection, and candidate-only output;
2. `m21_governed_relations.build_governed_candidate_packet` for exact Foundation relation ontology,
   controlled tag taxonomy, endpoint resolution, direction, inverse semantics, confidence ceilings,
   duplicate rejection, and governed candidate output.

M23.3 does not introduce a weaker parallel validator.

## Candidate authority

All extraction, relation, and tag outputs remain:

- `status: pending_review`;
- `authority: candidate_only`;
- `canonical_knowledge: false`;
- `production_authority: false`;
- `review_required: true`.

No candidate is accepted, written into Source, compiled, published, or shown in a Runtime graph by
this milestone. M23.4 owns entity resolution, human decisions, and the bounded Source PR.

## Scope exclusions

No external provider API call, credential use, Source mutation, review approval, canonical adoption,
embedding generation, R2 write, candidate or production publication, production pointer, traffic
change, multi-hop activation, Graph Explorer deployment, or Graph Neural Retrieval.

## Closure reconciliation

M23.3 was reconciled against the real six-document extraction evidence and live GitHub state.

- authoritative issue: #371;
- implementation PR: #372;
- exact entry Engine: `c9a91bfbe21ee107b80cd79644cb398c9abbed95`;
- rejected implementation head: `9f05f0563065cb950fb068de21bf9c0f58fb3de7`;
- accepted implementation head: `902c40a39a487a798e7a708ff00409d8b8621327`;
- expected-head implementation merge: `daf43375c80b998c156f3684eb584e8c21cf80d9`;
- implementation branch: `agent/m23-3-real-ai-extraction`;
- reconciliation branch: `docs/m23-3-real-ai-extraction-reconciliation`.

The accepted implementation diff contains exactly nine files:

- `.github/workflows/m23-3-real-ai-extraction.yml`;
- `docs/architecture/m23/m23-3-real-ai-extraction.md`;
- `pilot/m23/m23-3-real-ai-extraction-receipt.json`;
- `pyproject.toml`;
- `src/knowledge_engine/m23_real_ai_extraction.py`;
- `src/knowledge_engine/m23_real_ai_extraction_cli.py`;
- `tests/fixtures/m23/checkpoint.json`;
- `tests/fixtures/m23/plan.json`;
- `tests/test_m23_3_real_ai_extraction.py`.

The first head passed the dedicated M23.3 gate but CI #754 correctly rejected an accidental
`pyproject.toml` regression that removed an existing M16 `SIM102` exemption. The accepted head
restored only that pre-existing configuration and passed M23.3 #2, CI #755, M17 Architecture #111,
M18 Graph v2 #191, R2 Release Integration #506, R2 Canary #235, M23.2 #4, and every triggered
M16/M17 safeguard. PR #372 had no comments, reviews, or unresolved review threads.

The bounded evidence package SHA-256 is
`910abb34601f6425f05cdaf23e2d27e4ba42e462937175721b20d5a3f0356b2f`.
Source and Foundation remained unchanged. M23.4 review and Source-PR work has not started.

Production mutation dispatched: false.
