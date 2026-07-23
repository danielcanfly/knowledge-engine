# M25.9 Live Preflight Repair and Full-Population Pilot

## Proven root cause

The exact-SHA read-only diagnostic run `30039294894` used `main@ee622bfd7486fd6b3d29f585749b967657165f34` and performed zero Cloudflare mutations.

It proved:

- `CLOUDFLARE_API_TOKEN` is present and passes user-token verification;
- the same token returns HTTP `403` and Cloudflare code `10000` for Pages projects, Pages deployments, Access applications and the Access organization;
- `CLOUDFLARE_PAGES_ACCESS_TOKEN` is absent from the effective GitHub environment/repository secret scope;
- `CLOUDFLARE_ACCESS_READ_TOKEN` is absent from the effective GitHub environment/repository secret scope;
- the blocker is credential permission/resource scope, not the account-ID shape, Cloudflare availability or a request-body parsing error.

The previous workflow hid this evidence because it selected `dedicated || generic` silently and used `curl -f`, which discarded the Cloudflare error body.

## Repaired credential topology

The M25.9 pilot uses three explicit credentials and never falls back silently:

| GitHub environment secret | Purpose | Minimum Cloudflare authority |
|---|---|---|
| `CLOUDFLARE_PAGES_TOKEN` | Read, deploy and roll back the existing Pages project | Account `Pages Write`, scoped to the exact account |
| `CLOUDFLARE_WORKERS_TOKEN` | Read/deploy/delete the candidate Worker and manage its route | Account `Workers Scripts Write`; zone `Workers Routes Write` and `Zone Read`, scoped to `danielcanfly.com` |
| `CLOUDFLARE_ACCESS_READ_TOKEN` | Read the exact Access application and Zero Trust organization | Account `Access: Apps Read` and `Zero Trust Read`, scoped to the exact account |

The existing `CLOUDFLARE_ACCOUNT_ID` remains the account identity. Secret values must be entered only in GitHub Settings and must never be pasted into issues, pull requests, logs or chat.

## Repair behaviour

The new workflow is additive and leaves the failed historical workflow untouched for auditability.

Before any embedding, Qdrant, R2, Worker or Pages mutation, the dedicated preflight job:

1. requires run attempt `1` and the exact merged SHA;
2. verifies every dedicated token independently;
3. lists the exact Pages project and captures the previous production deployment;
4. lists Workers scripts, resolves the exact active zone and verifies Workers route access;
5. finds the exact Access application for `m24-internal.danielcanfly.com`;
6. verifies the Access organization and auth-domain binding;
7. records HTTP status, Cloudflare success, bounded error code/category and retry attempts;
8. uploads only sanitized evidence;
9. exits before external mutation if any capability is missing.

Network errors, HTTP `429` and HTTP `5xx` receive bounded retries. HTTP `401`, `403` and `404` are terminal evidence, not retry candidates.

## Full-population pilot gates

After preflight passes, the workflow preserves the existing accepted construction and deployment sequence:

- 156 admitted Sources;
- 4,222 graph nodes;
- 8,525 graph edges;
- 4,197 semantic documents;
- BGE-M3 vectors with dimension 1,024;
- full 4,197-point Qdrant readback;
- immutable R2 candidate release;
- disabled-first Worker deployment and secret binding;
- authenticated internal Pages deployment;
- unauthenticated Access denial checks;
- unchanged production pointer hash and no public-production traffic mutation;
- bounded rollback on any failure.

A successful automated run ends at `deployed_awaiting_authenticated_owner_acceptance`. M25.9 remains open until Daniel completes the authenticated browser acceptance and the final evidence is reconciled.

## Trigger boundary

The repair pull request must remain unmerged until all three dedicated GitHub environment secrets exist. Merging its exact reviewed head is the one push-generated attempt-1 trigger for the full-population pilot. The failed historical run `30032170246` must never be rerun.
