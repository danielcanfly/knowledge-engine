# M23.6.5 Read-Only Candidate Semantic Runtime and Shadow Endpoint

## Decision

M23.6.5 adds a deployment-ready, disabled-by-default Cloudflare Worker that can perform bounded semantic retrieval against the non-production M23 Qdrant collection. It does not deploy the Worker, create a Cloudflare Access application, call Workers AI, query Qdrant, or alter production retrieval.

The production authority remains `RETRIEVAL_MODE=lexical`. Semantic results are candidate-only evidence. The shadow route compares caller-supplied lexical point IDs with semantic rankings and returns diagnostics without replacing or mutating the lexical result.

## Internal surface

- Worker: `llm-wiki-m23-candidate-runtime`
- Retrieval: `POST /internal/candidate/m23/retrieve`
- Shadow: `POST /internal/candidate/m23/shadow/retrieve`
- Public route: forbidden
- `workers_dev`: false
- Preview URLs: false
- Runtime flag: `CANDIDATE_RUNTIME_ENABLED=false`
- Shadow flag: `SHADOW_SEMANTIC_ENABLED=false`

Both routes require a valid `Cf-Access-Jwt-Assertion`. The Worker validates its signature against the configured Cloudflare Access team JWKS and verifies the exact issuer and application audience before processing the request.

## Bounded query path

1. Reject unknown paths, non-POST requests and request bodies larger than 16 KiB.
2. Validate the versioned query object, a maximum 2,000-character query and `top_k` between 1 and 20.
3. Validate Cloudflare Access JWT issuer, audience and signature.
4. Generate one BGE-M3 query embedding and normalize it to unit length.
5. Issue one read-only Qdrant Query Points call against `llm_wiki_m23_pilot_bge_m3_1024` using named vector `default`.
6. Filter on the frozen pilot release identity, evaluation-only source membership and all authority flags false.
7. Request payloads but never vectors.
8. Validate every returned payload, score and release identity fail-closed.
9. Sort ties deterministically by point ID and emit provenance plus query and response fingerprints.
10. Refuse responses larger than 256 KiB.

## Shadow semantics

The shadow request includes up to 20 unique lexical point IDs. The response preserves those IDs in their original order and computes overlap, lexical-only IDs, semantic-only IDs and rank deltas. It explicitly records:

- lexical output remains authoritative;
- semantic output is not served to production;
- no answer generation occurred;
- no Qdrant write or production mutation occurred.

## Failure model

- Invalid request or Access token: fail closed.
- Placeholder Access configuration: unavailable, never bypassed.
- Invalid embedding, Qdrant timeout, malformed result or payload authority drift: generic candidate-runtime unavailable response.
- Runtime or shadow flag disabled: 404, hiding the internal surface.

## Authority boundary

This milestone dispatches no deployment, Access configuration, Workers AI inference, Qdrant read or write, Source change, Source PR #19 merge, R2 change, pointer change, production traffic change, permanent-ledger mutation, deletion, credential rotation, public Graph Explorer or Graph Neural Retrieval.

A later deployment requires separate explicit authority and current read-only preflight. Production remains lexical even after any candidate deployment.
