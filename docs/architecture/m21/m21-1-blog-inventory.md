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
