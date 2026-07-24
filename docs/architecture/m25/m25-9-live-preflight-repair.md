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

The M25.9 pilot uses four explicit credential roles and never falls back silently:

| GitHub environment secret | Purpose | Minimum Cloudflare authority |
|---|---|---|
| `CLOUDFLARE_API_TOKEN`, exposed only as `CLOUDFLARE_AI_TOKEN` | Run BGE-M3 embedding through the Workers AI REST API | Account `Workers AI Read` and `Workers AI Edit`, scoped to the exact account |
| `CLOUDFLARE_PAGES_TOKEN` | Read, deploy and roll back the existing Pages project | Account `Pages Write`, scoped to the exact account |
| `CLOUDFLARE_WORKERS_TOKEN` | Read/deploy/delete the candidate Worker and manage its route | Account `Workers Scripts Write`; zone `Workers Routes Write` and `Zone Read`, scoped to `danielcanfly.com` |
| `CLOUDFLARE_ACCESS_READ_TOKEN` | Read the exact Access application and Zero Trust organization | Account `Access: Apps and Policies Read` plus `Access: Organizations, Identity Providers, and Groups Read`, scoped to the exact account |

The existing `CLOUDFLARE_ACCOUNT_ID` remains the account identity. The Workers AI source secret is exposed to the candidate build only through the role-specific `CLOUDFLARE_AI_TOKEN` alias and is never used as a Pages, Workers management or Access fallback. Secret values must be entered only in GitHub Settings and must never be pasted into issues, pull requests, logs or chat.

## Repair behaviour

The new workflow is additive and leaves the failed historical workflow untouched for auditability.

Before any embedding, Qdrant, R2, Worker or Pages mutation, the dedicated preflight job:

1. requires run attempt `1` and the exact merged SHA;
2. verifies every dedicated token independently;
3. validates the BGE-M3 Workers AI model schema with the role-specific AI credential;
4. lists the exact Pages project and captures the previous production deployment;
5. lists Workers scripts, resolves the exact active zone and verifies Workers route access;
6. finds the exact Access application for `m24-internal.danielcanfly.com`;
7. verifies the Access organization and auth-domain binding;
8. records HTTP status, Cloudflare success, bounded error code/category and retry attempts;
9. uploads only sanitized evidence;
10. exits before external mutation if any capability is missing.

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

The repair pull request must remain unmerged until all four credential roles exist in the GitHub environment. Merging its exact reviewed head is the one push-generated attempt-1 trigger for the full-population pilot. The failed historical run `30032170246` must never be rerun.

## BGE-M3 context-budget repair authority

Full-population inference-only scan run `30065403198` at exact SHA
`eeaecfdfd95d6113b9d75013ccea47a3a829113b` scanned 3,975 semantic
documents before isolating batch indexes `3950..3974`. Cloudflare returned
HTTP `400`, code `3030`: the 25 complete inputs required 80,825 tokens while
the managed BGE-M3 context supports 60,000. Every input in that batch passed
individually. The scan performed zero Qdrant, R2, deployment, production
pointer or public-traffic mutations.

The repair preserves every admitted input without truncation. Deterministic
initial batches are bounded by both 100 inputs and 16,000 normalized text
characters. If Cloudflare still reports the explicit context-limit condition,
only that batch is split into ordered halves recursively. All unrelated HTTP
errors remain terminal, and a single-input context failure remains terminal.

Compatibility publisher run `30068729673` verified the repair against the
repository's established response adapters. The implementation now uses
`raise_for_status()` as the terminal HTTP contract and a defensive
`status_code` fallback only for identifying context-limit responses, while
preserving recursive code `3030` splitting and input order.


## R2 object-write capability gate

Fresh full-pilot run `30068964353` passed Cloudflare preflight, Workers AI
capability, production-pointer read, embedding, and Qdrant verification, then
failed at R2 `PutObject` with `AccessDenied`. The same credentials successfully
read `channels/production.json`, proving the endpoint, bucket and authentication
identity were valid for reads while object-write authority was absent.

Before any subsequent full-population embedding run, an independent bounded R2
gate must create one unique canary under `diagnostics/m25-9/r2-write-preflight/`,
read it back and verify its digest, delete it, and confirm that no residual object
remains. A successful check performs exactly two bounded candidate mutations
(one put and one delete) with zero residual objects. Production channel keys and
public-production traffic remain untouched.

The GitHub environment `m23-r3-diagnostic` must contain R2 S3 credentials with
**Object Read & Write** (or Admin Read & Write) permission scoped to the exact
bucket named by `R2_BUCKET`. Read-only credentials are not sufficient. Rotate
both `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` together; the secret access key
cannot be viewed again after token creation.

