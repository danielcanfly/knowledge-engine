# M21.1 blog inventory and bounded connector

## Status

Implementation contract for issue #312. M21.1 establishes Phase D with deterministic inventory evidence and a bounded connector descriptor. It does not perform a live whole-site crawl and grants no Source, candidate, or production authority.

## Connector preference

The preferred source order is:

1. exact repository Markdown;
2. complete site API;
3. complete site feed;
4. bounded HTTPS canonical URL capture.

Browser extraction is excluded from M21.1.

The connector object is a request descriptor, not a network client. It records source kind, canonical URL, host, media type, byte limit, redirect limit, and the fact that public inventory requires no credentials.

## URL and network boundary

Only HTTPS URLs on explicit allowlisted hosts are accepted. The contract rejects:

- URL userinfo or embedded credentials;
- fragments;
- non-canonical ports;
- private, loopback, link-local, reserved, or otherwise non-global IP addresses;
- hosts outside the allowlist;
- redirect chains longer than eight hops;
- redirect loops or redirect host escapes;
- declared payloads larger than 8 MB;
- unsupported media types.

M21.1 contains no HTTP client, DNS resolution, browser automation, R2 client, or production secret path.

## Inventory record

Each item records:

- canonical URL;
- language;
- slug;
- series and part;
- trustworthy publication and modified timestamps when available;
- content SHA-256;
- source kind and exact locator;
- redirects;
- translated counterpart;
- access status;
- intake status;
- ownership or licence basis;
- audience.

The snapshot binds these records to exact Engine, Source, and Foundation SHAs plus UTC capture time.

## Determinism and integrity

URLs and timestamps are normalised deterministically. Records are sorted by canonical URL. The snapshot digest is computed from canonical JSON before the digest field is added.

The builder fails closed on:

- invalid repository identities;
- invalid timestamps or content digests;
- duplicate canonical URLs;
- duplicate content digests;
- redirect loops;
- missing or excessive items;
- malformed locators or ownership basis;
- unsupported source kinds;
- invalid audience, access, or intake status.

Duplicate content is evidence requiring review, not a reason to silently create multiple canonical concepts.

## Authority boundary

The snapshot declares:

- `authority: evidence_only`;
- `canonical_knowledge: false`;
- `production_authority: false`.

It may be consumed by M21.2 resumable batch preparation, but it cannot mutate Source, create concepts, publish releases, update production pointers, retain R2 objects, write permanent ledgers, or dispatch rollback.

## Acceptance

M21.1 acceptance covers:

- deterministic URL canonicalisation;
- bounded and credential-free connector descriptors;
- HTTPS, host, port, media, payload, redirect, and SSRF controls;
- stable inventory sorting and snapshot digest;
- UTC timestamp normalisation;
- duplicate URL and content detection;
- redirect loop and host-escape rejection;
- exact Engine, Source, and Foundation identity binding;
- evidence-only and non-production authority;
- M20 and Runtime regressions.

## Exclusions

No live whole-site ingestion, browser extraction, entity or concept extraction, relation extraction, resumable batch execution, Source edit, candidate or production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.2 work, cross-release merge, or Graph Neural Retrieval is included.

## Closure reconciliation

M21.1 implementation PR #314 was based on exact Phase C closure `ec7962edb13807246c752aee029148515a9a496a` and merged at `c6471e6bcbedc9a0c78a59185bc84074accefa0e` from final expected head `ce673c919cb6d32c62e2f7ed1c5183410b95ff5f`.

The implementation changed exactly four files: this architecture contract, the M21.1 workflow, the inventory module, and its acceptance tests. Final-head workflows were all green: M21.1 Blog Inventory #4, CI #656, M17 Architecture Canon Acceptance #60, M18 Graph v2 Acceptance #92, and R2 Release Integration #454. PR comments, reviews, and unresolved threads were empty.

Two earlier heads are invalidated and provide no acceptance evidence:

- `a22bc20f62ad2133104a15582a9047e4bdc8b7e0`, rejected by repository Ruff formatting and `datetime.UTC` rules;
- `978db6b8f13e6aee03478b9ab6c36b1b6a9e3454`, where all tests passed but the shell authority scan incorrectly used `! find`.

Source remained `a6ba738d910d01d2ae99b1968f0831989934c549` and Foundation remained `e5ef644053d34e89c70d2ceb37521e1c59234832`. No live crawl, Source mutation, publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.2 implementation, cross-release merge, or Graph Neural Retrieval was dispatched.
