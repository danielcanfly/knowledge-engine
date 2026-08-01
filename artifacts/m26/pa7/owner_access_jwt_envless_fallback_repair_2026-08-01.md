# M26 PA7 owner Access JWT envless fallback repair

Generated: 2026-08-01

## Problem

Daniel's normal Chrome session could pass the Cloudflare Access browser gate but the Ask owner API still returned `M26_OWNER_ACCESS_JWT_CONFIG_MISSING`.

That means the deployed Pages Worker received a Cloudflare Access JWT but did not have `ACCESS_TEAM_DOMAIN` / `ACCESS_AUD` available in the Pages runtime environment. Previous PRs repaired JWT verification but still fail-closed before verification when those bindings were absent.

## Repair

`pilot/m24/internal-product-deployment/site/_worker.js` now resolves the Cloudflare Access JWT verification contract in this order:

1. Use configured `ACCESS_TEAM_DOMAIN` / `ACCESS_AUD` when present.
2. If those runtime bindings are absent, decode only the unsigned JWT payload to infer `iss` and exactly one `aud`.
3. Require the inferred issuer hostname to be Cloudflare Access (`cloudflareaccess.com` or `*.cloudflareaccess.com`).
4. Verify the JWT signature using the inferred issuer JWKS endpoint.
5. Verify issuer, audience, expiry and not-before.
6. Only after cryptographic verification, read the email claim and compare its SHA-256 to `M26_OWNER_EMAIL_SHA256`.

## Boundaries

- No service-token owner bypass.
- No public pages.dev bypass; pages.dev host remains forbidden.
- No password, OTP, cookie, JWT or token exposure.
- No R2 writes.
- No Qdrant writes.
- No production pointer writes.
- No canonical corpus/index mutation.

## Expected result

The owner browser evidence extension should no longer fail at owner health solely because Pages runtime lacks `ACCESS_TEAM_DOMAIN` / `ACCESS_AUD`.
