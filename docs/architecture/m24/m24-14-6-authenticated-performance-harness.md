# M24.14.6 Authenticated Performance Harness

M24.14.6 Stage A adds the benchmark harness needed before final M24.14 acceptance.
It does not close final acceptance by itself.

## Authority

- Production retrieval remains lexical.
- Semantic and hybrid production serving remain disabled.
- Cloudflare Access remains the human gate.
- Local and CI browser regression has only `local_exact_site_browser_regression`
  authority.
- Only a sanitized result with `authenticated_live` authority can be used for the
  final performance decision.

## Daniel Gate

Stage A leaves exactly one Daniel action:

```bash
python scripts/m24_14_6_authenticated_benchmark.py --headed --capture-auth
```

Daniel logs into the protected Cloudflare Access browser session and returns only
the generated sanitized JSON. The harness rejects cookies, authorization values,
tokens, email-like strings, raw headers, profile paths, and account identifiers.

## Stage A Artifacts

- `pilot/m24/m24-14-6/benchmark-policy.json`
- `pilot/m24/m24-14-6/benchmark-cases.json`
- `pilot/m24/m24-14-6/m24-14-5-human-acceptance.json`
- `pilot/m24/m24-14-6/m24-14-6-pending-acceptance.json`
- `pilot/m24/internal-product-deployment/site/data/m24-14-6-pending-acceptance.json`

The site exposes an authenticated Acceptance Status route so the pending gate is
visible inside the protected product surface without weakening Access.

