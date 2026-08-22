# M26 Translation Gateway Non-Promotional Staging

Date: 2026-08-21

## Status

Status: translation gateway candidate, not production ready.

Candidate SHA:

```text
291ef67111e3e27ad0665114f35660618c09544a
```

Accepted sealed English base:

```text
303b933a84be567571808025f8b4331b7edee105
```

## Passed

- Independent held-out semantic qualification: `HELDOUT_PASS_ZERO_BLOCKERS`
- Deterministic Phase B plumbing: `PHASE_B_DETERMINISTIC_PLUMBING_PASS`

## Not Passed

- Live Phase B downstream parity

Reason:

- `SEALED_ENGLISH_DOWNSTREAM_BASELINE_UNSTABLE`
- Earliest divergence: `SEMANTIC_CLOSURE_GENERATION_DIVERGENCE`

## Production Enablement

Production enablement is disabled and not authorized.

Do not use this staging integration to:

- enable public production serving;
- switch a production route;
- declare production readiness;
- change sealed English M26 runtime semantics;
- add answer-back translation;
- add NMT fallback;
- add hidden translation retry;
- hide the live Phase B invalid status.

## Staging Entrypoint

Use `docker-compose.translation-gateway-staging.yml` only for local or review staging.

The service binds to loopback:

```text
127.0.0.1:18083
```

The staging health endpoint is:

```text
/v1/translation-gateway/health
```

The staging query endpoint is:

```text
/v1/translation-gateway/query
```

Requests remain owner/backend-authorized through the existing M26 owner-only auth path. The translation gateway accepts only `question` as a request body field and does not expose provider or model selection.

## Separate Blocker Track

The remaining production blocker is sealed English live downstream instability, isolated to provider-backed semantic closure generation. Remediation for that blocker must be handled in a separate sealed-English stability track and must not be bundled into this translation gateway staging PR.
