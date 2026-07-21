# M24.14.1 Product Application Shell

M24.14.1 replaces the prior static JSON catalogue with a real browser-loadable
internal product shell in the existing Pages deployment package.

## Delivered

- self-hosted JavaScript module application;
- no runtime CDN dependencies;
- same-origin canonical artifact loading;
- release identity validation before rendering;
- routes for overview, Concept Wiki, lexical search, Graph Explorer, sources,
  release details and Obsidian export;
- loading, missing-artifact, release-mismatch, ACL-denied, no-match and bounded
  error states;
- read-only authority and lexical-only production retrieval boundary;
- local HTTP smoke and Playwright route screenshot evidence.

## Boundary

This phase does not deploy the product, mutate Cloudflare, change DNS, alter
Cloudflare Access policy, promote production semantic/hybrid retrieval, serve
production answers, mutate Source/Foundation/R2/Qdrant, or claim Daniel browser
acceptance.

The Graph route in M24.14.1 is a canonical graph preview and textual fallback.
Real Sigma.js interaction is intentionally reserved for M24.14.2.

## Evidence

Machine-readable evidence:

`pilot/m24/m24-14/product-app-shell/m24-14-1-product-app-shell.json`

Key implementation files:

- `pilot/m24/internal-product-deployment/site/index.html`
- `pilot/m24/internal-product-deployment/site/app.js`
- `pilot/m24/internal-product-deployment/site/styles.css`

Primary tests:

- `tests/test_m24_14_1_product_app_shell.py`
- `tests/test_m24_p6_internal_product_deployment.py`
