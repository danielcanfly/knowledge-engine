# M14.1 Public Query API and Contracts

Status: implementation candidate  
Parent: #190  
Slice: #191  
Engine baseline: `249a0a7d6e111392a99678daf170196ac518d298`

## Purpose

M14.1 introduces a stable public answer envelope for blog, chat and API clients. It deliberately separates the public product contract from the internal runtime retrieval and evaluation payloads.

The existing `/v1/query` endpoint remains available for internal compatibility. The new public endpoint is:

```text
POST /v1/ask
```

## Request

```json
{
  "query": "How does the knowledge compiler publish a release?",
  "max_results": 5,
  "audience": "public"
}
```

The requested audience must be present in the authenticated principal. A caller cannot request a broader audience merely by changing the JSON field.

## Response

Every successful `/v1/ask` response contains exactly the product-level fields:

```text
schema_version
answer
status
citations
concept_ids
release_id
request_id
audience
confidence
not_found_reason
```

The public response intentionally excludes:

- manifest internals;
- retrieval candidates and score traces;
- evaluation-policy internals;
- hidden ACL-filtered concepts;
- cache paths and object keys;
- raw exception text.

## Status model

- `answered`: authorized results and citations are available;
- `degraded`: authorized result text exists but citation coverage is missing;
- `not_found`: no authorized result exists.

`not_found_reason` is explicit and bounded:

- `no_match`;
- `no_authorized_match`;
- `release_unavailable`.

## Deterministic request identity

`request_id` is a SHA-256-derived identity over:

- normalized query text;
- requested result limit;
- effective audience;
- exact release ID;
- exact manifest SHA-256.

The same request against the same immutable release replays to the same identity. A release change necessarily changes the request identity.

## Answer composition

M14.1 does not introduce an ungoverned generative model. The answer is composed deterministically from the top authorized wiki sections. This provides a stable product contract before later M14 interfaces add richer presentation and optional answer-generation policy.

## Citation contract

The initial citation object contains:

```text
source_id
uri
retrieved_at
concept_id
section_id
```

M14.3 may enrich this object with source-card presentation fields without changing the core release and concept binding.

## Confidence

Confidence is deterministic and bounded from zero to one. It combines retrieval score, selected-result coverage and citation availability. It is a product indicator, not a claim of statistical calibration.

## Error contract

Public endpoint errors use:

```text
knowledge-engine-public-query/v1/error
```

The payload contains a stable code, a safe message and an optional request ID. Internal exception strings and storage locations are not returned.

## Governance boundary

M14.1 performs no Source write, release creation, production mutation, ledger append, rollback or raw-evidence access. It reads the already active immutable release through the existing runtime.
