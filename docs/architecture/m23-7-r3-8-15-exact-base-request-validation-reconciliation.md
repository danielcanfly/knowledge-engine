# M23.7-R3.8.15 independent exact-base request validation reconciliation

Implementation PR #581 accepted head `119955c0f41fbdb4a0408a26b86531bbfbb2094c` and merged as `4ccc139a73dcae18bd904222f115e533c73cada4`.

Independent review confirms an exact five-file implementation scope. The request validator, push-triggered execution workflow, recovery runtime, telemetry writer and v1-v3 authorizations remain unchanged.

Request PR #579 was never merged. Its request schema, canonical digest, nonce and committed authorization had passed. The sole rejection was the historical scope check's dependence on the local branch name `main`. No request push or Cloudflare access occurred.

The repaired request-only scope uses exact event identities:

```text
BASE_SHA = github.event.pull_request.base.sha
HEAD_SHA = github.event.pull_request.head.sha
```

It validates both SHAs, exact checked-out HEAD, base ancestry and the exact changed path set. The implementation contains no `GITHUB_BASE_REF` dependency. A dedicated regression proved the diff succeeds in detached-HEAD state with no local `main` ref.

Fresh v4 authorization SHA-256:

```text
1375bf49d53ce7b8cc63bfc83c2e409e8458e40bdde3bc22952e0750f96de8a8
```

Repair contract SHA-256:

```text
a3edc3cd607d3a71eea48db7bfcccf1a8f9c5f4500cd5abd06595f5f5786e032
```

Independent reconciliation SHA-256:

```text
3730591f57c17c16d735c5f400ef5f2a09addb8e2a3769cdecd9023128fac522
```

All implementation workflows succeeded:

- exact-base gate `29526210333`;
- request-ledger regression `29526209674`;
- global CI `29526209336`;
- M17 `29526209713`;
- M18 `29526209620`.

After this reconciliation merges, a fresh v4 request must be generated from the reconciliation merge SHA. Production retrieval remains lexical and both blockers remain active. No execution request, blocker clearance, promotion or closure is authorized by this reconciliation.
