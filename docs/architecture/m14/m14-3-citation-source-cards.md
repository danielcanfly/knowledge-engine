# M14.3 Citation Payload and Source Cards

Status: implementation candidate  
Parent: #190  
Slice: #194  
Depends on: M14.1 #191 and M14.2 #192  
Engine baseline: `b7edeb041a4a09d2900fce97a98fb8cfb61bcec2`

## Purpose

M14.3 turns the M14.1 citation list into an inspectable product contract. A citation now points to the exact selected wiki section, the supporting provenance claim when one exists, a bounded source locator and a release-bound source card.

The source card is a rendering contract, not a new retrieval or storage surface. It never fetches a URL, opens a snapshot or reads an arbitrary object key.

## Runtime claim-to-evidence mapping

After M14.2 selects the best authorized section for each concept, runtime performs a second provenance pass.

A claim matches the selected section when either:

- `selector.section_id` equals the selected section ID; or
- normalized `selector.heading` equals the selected section title.

For matching claims, runtime follows each evidence `source_ref` to the provenance source catalog and produces a claim-level citation candidate containing:

```text
source identity
source presentation metadata
retrieval and optional publication time
source content integrity identity
snapshot availability boolean
concept and section identity
claim identity and confidence
support type
evidence locator
review and derivation metadata
```

The snapshot object key itself is not copied into the runtime result.

If no claim selector matches the selected section, runtime preserves compatibility by producing concept-level citations from the authorized concept sources. The citation scope makes this distinction explicit:

```text
claim
concept
```

## Source-level authorization

Concept authorization does not automatically authorize every underlying source.

Runtime determines source audience in this order:

1. explicit source audience;
2. a single valid `access.source_audiences` value;
3. concept audience for non-declassified legacy records.

A declassified record with no source audience fails closed and treats the source as restricted. Source authorization is checked after section selection and before any source metadata enters the public formatter.

The internal retrieval trace records:

```text
citation_source_acl_filtered_count
claim_citation_candidate_count
concept_citation_candidate_count
citation_candidate_count
```

## Public citation identity

Every public citation receives a deterministic ID:

```text
cite_{sha256-prefix}
```

The identity includes:

- exact release ID;
- source-card ID;
- concept ID;
- section ID;
- citation scope;
- support type;
- bounded locator;
- sorted claim IDs.

The same immutable release and evidence replay to the same citation ID. A release change necessarily changes the citation ID.

## Source-card identity

Every source card receives:

```text
card_{sha256-prefix}
```

Its identity includes:

- exact release ID;
- source ID;
- canonical public URI;
- source content SHA-256 when available.

Multiple citations to the same source are grouped into one card. The card aggregates citation IDs, concept IDs, section IDs and claim IDs.

## Answer markers

Citations receive deterministic one-based ordinals in result order. The public answer appends markers to the exact answer segment supported by those citations:

```text
Knowledge Compiler · Operational rule: ... [1]
```

A segment may carry multiple markers. When all source candidates are suppressed, the answer remains available with status `degraded` and contains no marker.

## Citation contract

The public citation schema is:

```text
knowledge-engine-public-citation/v1
```

Fields:

```text
citation_id
ordinal
source_card_id
source_id
source_kind
uri
retrieved_at
concept_id
section_id
citation_scope
claim_ids
support
locator
claim_confidence
review_status
derivation_type
```

The locator is an allowlisted object. Supported fields are:

```text
heading
page
paragraph
start_line
end_line
timecode
anchor
```

Unknown fields, quoted source text and oversized values are omitted.

## Source-card contract

The public source-card schema is:

```text
knowledge-engine-source-card/v1
```

Fields:

```text
source_card_id
ordinal
source_id
title
publisher
display_host
source_kind
uri
retrieved_at
published_at
snapshot_available
integrity_sha256
citation_ids
concept_ids
section_ids
claim_ids
```

`ordinal` is the first citation ordinal associated with the card.

## Public URI policy

Only safe HTTP and HTTPS URIs may enter a public citation or source card.

The formatter rejects:

- non-HTTP schemes;
- username or password components;
- localhost and private, loopback, link-local, multicast or reserved IP addresses;
- `.local`, `.internal` and `.localhost` hosts;
- query fields containing credentials, tokens, secrets or signatures.

Accepted query fields are sorted deterministically and URL fragments are removed. The formatter performs no DNS request and no remote fetch.

## Presentation fallback

Rich source metadata is optional for legacy provenance.

When title or publisher is absent:

- title falls back to the public display host, then source ID;
- publisher falls back to the public display host;
- source kind defaults to `web`;
- citation scope defaults to `concept`;
- support defaults to `context`.

## Public response compatibility

M14.3 keeps the M14.1 response schema identity and all existing fields. It enriches citation objects and adds:

```text
source_cards
```

The response still excludes runtime retrieval traces, provenance records, manifest internals, snapshot keys, raw source bodies, storage paths and signed URL secrets.

## Governance boundary

M14.3 performs no Source write, release creation, production mutation, rollback, ledger append, snapshot read, connector call or physical deletion. It transforms provenance already present in the active immutable release into a bounded public payload.
