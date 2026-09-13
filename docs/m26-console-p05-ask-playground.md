# M26 Console P05 Ask Playground backend

This branch adds only the page-specific owner-console adapter for P05 Ask Playground.

## Baseline

- Stacked on SM-B01 admin control-plane head: `7e03d03f196824049b95d0378ee13d1e28292f94`.
- Public Ask API contract and route are not modified.
- Canonical P05 admin endpoints are `/v1/admin/playground/retrieve` and `/v1/admin/playground/ask`.

## Safety invariants

- Retrieval-only stops after qualified evidence selection and structurally performs zero generation-provider calls.
- Full Ask passes an explicit synthesis provider with `max_calls=1`, bypassing the public adapter's fallback routing path after the cost boundary.
- Console Access authorization and the frozen PA7 runtime owner binding remain distinct identity domains. The PA7 owner binding is server-side only.
- English translation bypass does not require a translation provider to be constructed.
- Dense retrieval degradation, translation failures, and provider failures retain stable reason codes in the page trace and availability envelope.
- `observed_at` remains null when the adapter has no authoritative source observation timestamp.
- Both P05 endpoints are non-state-changing under the canonical Gate-A contract.

## Validation

Successful branch validation run: GitHub Actions `33890318197` on validation head `78cb9b855c965493b48d2b146638a5683a23dc4b`.

- Ruff: PASS.
- Focused pytest: 24 passed, 2 dependency deprecation warnings.
- FastAPI OpenAPI route-registration smoke: PASS.

The product source and tests validated by that run are byte-identical to the final branch versions. Subsequent commits remove the temporary branch-only workflow and add this handoff note only.

No deployment, DNS/Access mutation, R2/Qdrant write, or production-pointer mutation was performed.
