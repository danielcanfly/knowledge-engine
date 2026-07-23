# M26.2 Retrieval Envelope and Evidence Assembly

**Issue:** #1058  
**Entry Engine SHA:** `d3cf8cc72d951174f10c0a8328f848143c24e004`  
**Accepted predecessor:** `m26_1_architecture_authority_accepted`  
**Target after independent reconciliation:** `m26_2_retrieval_envelope_accepted`

## 1. Purpose

M26.2 creates the deterministic bridge between a release-pinned question and the future M26.3 Context Compiler. It reuses the accepted M14 lexical retrieval, Graph v2 validation and citation/provenance surfaces, then packages exact authorised passages into the M26.1 `EvidenceEnvelope` contract.

This stage deliberately contains no LLM. Retrieval defects must be visible before generation can turn them into fluent prose.

## 2. Authority

M26.2 is synthetic and candidate-only.

Allowed:

- validate a closed M26.1 question request;
- build a deterministic retrieval plan;
- execute release-pinned lexical retrieval over committed synthetic fixtures;
- perform bounded compatibility-graph and approved Graph v2 expansion;
- apply ACL filtering before evidence text is exposed;
- assemble exact passages, relation paths, trace records and gap reports;
- benchmark deterministic quality, completeness and latency.

Forbidden:

- real corpus or production release binding;
- provider call, credential or model SDK;
- semantic or hybrid retrieval;
- production answer serving or unverified streaming;
- Source, Foundation, release, production pointer, R2 production or Qdrant mutation;
- canonical identity, relation, tag or review decisions.

## 3. Reuse, not a second retrieval stack

`knowledge_engine.m14_retrieval.retrieve_wiki_first` remains the accepted retrieval implementation. M26.2 supplies a versioned adapter that:

1. validates M26.1 release and audience identities;
2. constrains the accepted lexical and graph inputs;
3. invokes the accepted retrieval function with `semantic_index=None`;
4. invokes `m14_citation_runtime.enrich_runtime_citations`;
5. turns selected citation candidates into exact typed passages.

M26.2 does not create another index, graph authority, citation authority or raw-source fallback.

## 4. Retrieval plan

The plan is deterministic for the same request and policy:

- whitespace-normalised question;
- bounded intent classification;
- hierarchical allowed audiences;
- lexical lane always enabled and limited to ten synthetic candidates;
- Graph expansion enabled only for intents that need explanation, comparison, provenance or navigation;
- Graph depth one, 25 nodes and 50 edges;
- approved relation types only;
- exact release identity copied unchanged;
- canonical JSON SHA-256 deterministic key.

Unknown fields, unknown major versions, release drift and authority escalation fail closed.

## 5. ACL and evidence assembly

ACL filtering occurs before source text enters the envelope. A public request can never receive an internal, confidential or restricted passage. Filtered identities are represented by opaque hashes, preventing the diagnostic surface from leaking restricted source names.

Every included passage carries:

- source ID, kind and URI;
- concept and section identities;
- exact audience;
- extracted evidence text;
- text SHA-256 and synthetic snapshot SHA-256;
- typed heading/page/line/paragraph/timecode/anchor locator;
- deterministic passage identity and rank;
- lexical retrieval score;
- relation path references;
- prompt-injection warning codes.

Secret-like passages are excluded before persistence. Prompt injection is recorded as untrusted evidence and never obeyed.

## 6. Citation support

Citation presence is not claim support.

Claim-level citations with exact locators are the preferred material evidence. A concept-level citation may help navigation but cannot silently satisfy a material factual claim. Missing locators, stale sources, unsafe text and duplicates remain in the denominator as explicit exclusions.

Graph proximity is discovery metadata. Every relation path records `factual_support: false`; factual claims still require passage evidence.

## 7. Completeness and first divergent stage

M26.2 maps question terms to required synthetic facets and reports:

- required facet coverage;
- covered facets;
- missing facets;
- evidence sufficiency;
- first divergent stage;
- stable reason codes;
- next legal action.

The first divergent stage can be query planning, corpus, index, candidate recall, ACL, graph, citation locator, evidence assembly or sufficiency. This prevents a weak answer from triggering random changes to models, prompts or top-K.

A rich multi-facet query must retrieve evidence for retrieval quality, citation support, answer completeness and latency. The later Context Compiler receives that coverage record, so a rich evidence set cannot quietly collapse into a thin answer.

## 8. Sufficiency states

- `sufficient`: exact authorised claim passages cover all required facets.
- `partially_sufficient`: usable passages exist, but a required facet, qualifier or claim-level support is missing.
- `conflicting`: authorised evidence contains both supporting and contradicting material.
- `insufficient`: candidates exist, but exact safe passages cannot be assembled.
- `no_match`: no authorised lexical match exists.

Conflict is preserved for later disclosure. It is never resolved by retrieval score.

## 9. No silent exclusion

For every request:

```text
retrieved = included + excluded + acl_filtered
```

The envelope records stale, unsafe, duplicate, invalid, limited and ACL-filtered evidence separately. No candidate disappears simply because it was inconvenient.

## 10. Synthetic benchmark

The committed benchmark covers:

1. direct public retrieval;
2. M26.1 bounded-verification compatibility;
3. internal multi-facet depth;
4. Graph relation discovery;
5. public ACL negative and non-leakage;
6. stale evidence;
7. conflicting evidence;
8. prompt-injection containment;
9. genuine no-match.

The workflow also measures repeated in-process latency and rejects tail regressions. Latency evidence is observational and excluded from deterministic artifact identities.

## 11. Exit gate

M26.2 implementation is ready only when:

- all nine benchmark cases pass;
- deterministic rebuilds are byte-identical;
- exact passage hashes and locators validate;
- ACL leakage count is zero;
- semantic/hybrid use count is zero;
- provider-call count is zero;
- real-corpus binding count is zero;
- population accounting is complete;
- dedicated exact-head CI and inherited M26.1, M17 and M18 checks are green;
- protected mutations and unresolved review threads are zero.

Implementation merge alone does not authorise M26.3. A separate reconciliation must record `m26_2_retrieval_envelope_accepted`.

## 12. Next stage

After accepted reconciliation, M26.3 may implement the synthetic Context Compiler and evidence budget against this envelope. M26.3 still cannot bind a real corpus, call a provider or enable production answer serving.
