# M24.10 Authenticated Live URL Readiness

P7 moves the P6 internal product deployment package toward a live authenticated
internal URL without over-claiming a deployment that has not passed Access and
Daniel acceptance.

## Status

P7 status is:

`blocked_pending_cloudflare_pages_access_authority`

The local Cloudflare token can verify, read the account, and read active zones,
including `danielcanfly.com`. It cannot read or write Cloudflare Pages projects
or Cloudflare Access applications. Those API probes returned a bounded 4xx
authentication-error class. GitHub repository secrets also do not contain a
Cloudflare Pages or Access deployment token.

No token values, raw headers, raw error bodies, secret values, or account IDs are
committed.

## Intended Live Binding

- Pages project: `llm-wiki-m24-internal`
- Custom hostname: `m24-internal.danielcanfly.com`
- Source package: `pilot/m24/internal-product-deployment/site`
- Upload path: Cloudflare Pages Direct Upload with Wrangler
- Access application: Cloudflare Access self-hosted application
- Policy: Daniel internal operator identity or approved internal group
- Unauthenticated behavior: `403` or Access challenge

The exact upload command is recorded in the P7 evidence. It must not be treated
as accepted until Access is bound and Daniel has opened the authenticated URL.

## Required Authority

P7 needs a Cloudflare API token or CI secret with:

- Cloudflare Pages Write;
- Cloudflare Access Apps and Policies Write;
- Cloudflare Access Organization Read;
- Zone DNS Edit for `danielcanfly.com`.

The existing local token does not provide the Pages or Access authority needed
to complete this live binding.

## Readiness Checks

Before P7 can become live accepted:

- unauthenticated request to the custom hostname returns `403` or an Access
  challenge;
- authenticated request renders the exact canonical release banner;
- site artifacts match the P6 sha256 manifest;
- no browser network request leaves the static package except Access
  authentication;
- Daniel opens the authenticated URL and records manual acceptance.

## Public Exposure Controls

P7 must not rely on the public `pages.dev` URL as acceptance evidence. If a Pages
upload succeeds but Access binding fails, the deployment or project must be
deleted or disabled before closure.

## Boundary

P7 does not authorize production semantic or hybrid retrieval, semantic serving,
production answer serving, Source mutation, production pointer mutation, R2
mutation, Qdrant mutation, credential mutation, traffic mutation, or permanent
ledger mutation.

Production retrieval remains lexical. Semantic promotion remains a separate
decision gate.
