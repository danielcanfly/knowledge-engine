# M25.9 Cloudflare Preflight Diagnostic

## Purpose

This bounded diagnostic identifies which effective Cloudflare credential can read the exact Pages
and Access resources required by the M25.9 full-population candidate pilot. It replaces the previous
silent `dedicated || generic` selection with independently labelled probes.

## Authority boundary

The diagnostic performs only HTTP `GET` requests and uploads one sanitized GitHub Actions artifact.
It performs no R2, Qdrant, Worker, Pages, Access, DNS, Source, release, production-pointer or public
traffic mutation. Run attempt reuse is forbidden.

## Credential labels

- `pages_dedicated`: effective `CLOUDFLARE_PAGES_ACCESS_TOKEN`
- `access_dedicated`: effective `CLOUDFLARE_ACCESS_READ_TOKEN`
- `generic_cloudflare`: effective `CLOUDFLARE_API_TOKEN`

Secret values, authorization headers and raw response bodies are never written to evidence.

## Read-only probes

Each present credential is independently tested against:

1. user-owned token verification;
2. account-owned token verification;
3. Pages project listing;
4. production Pages deployment listing for `llm-wiki-m24-internal`;
5. exact-domain Access application lookup;
6. Zero Trust organization lookup.

The artifact retains HTTP status, Cloudflare success state, bounded error code and category, attempt
number, retryability, response digest and only the minimum non-sensitive resource-presence fields.
Retries are limited to network errors, HTTP 429 and HTTP 5xx responses.

## Decision contract

The diagnostic recommends one explicit topology:

- `explicit_dedicated_tokens` when separate Pages and Access credentials pass;
- `verified_generic_temporary` when one generic credential passes all required reads;
- `explicit_mixed` when a named Pages/Access split passes;
- `blocked` when no complete topology is proven.

The live workflow must not be repaired by guessing. Its next PR must use the exact successful labels,
preserve HTTP metadata before failure, require Cloudflare `success=true`, and retain attempt-1-only,
rollback and production-isolation boundaries.
