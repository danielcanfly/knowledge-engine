# M24.9 Internal Product Deployment

P6 packages the canonical M24 candidate release as an authenticated internal
product deployment bundle.

## Release Under Test

- Release ID: `20260720T160000Z-46137c97263e`
- Manifest SHA-256:
  `ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`

## Internal Product Bundle

The deployment package is:

`pilot/m24/internal-product-deployment/site/`

It contains read-only internal product data for:

- Concept Wiki;
- lexical search;
- Sigma Graph Explorer payload;
- provenance/source viewer;
- citation-grounded internal answers;
- release viewer;
- Obsidian export manifest.

The package includes an exact release banner, static textual fallback, explicit
error states, CSP-compatible static assets, and no write-back target.

## Authentication

P6 requires Cloudflare Access or an equivalent signed internal session before a
live URL can be treated as usable.

The committed deployment evidence records:

- authentication required;
- anonymous access denied;
- unauthenticated behavior: `403`;
- live URL status: `pending_cloudflare_access_binding`;
- Daniel manual acceptance: `pending_authenticated_url`.

This is deliberate: the repository has Cloudflare account/token material
available locally, but no committed Access application, domain, or audience
binding. P6 therefore completes the deployment package and safety evidence
without pretending that Daniel has opened an authenticated URL.

## Security And Operations

The evidence records:

- CSP:
  `default-src 'none'; style-src 'self'; img-src 'self'; connect-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`;
- no inline script authority;
- no remote browser network authority;
- secret scan passed;
- read-only browser authority;
- observability event names;
- release and citation error states;
- rollback plan.

## Boundary

P6 does not authorize:

- production semantic or hybrid retrieval;
- production answer serving;
- Source mutation;
- production pointer, R2, Qdrant, credential, traffic, or permanent-ledger
  mutation.

Production retrieval remains lexical. Semantic promotion remains a separate
decision gate.
