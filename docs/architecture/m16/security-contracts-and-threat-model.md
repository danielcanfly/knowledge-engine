# M16.1 Security Contracts and Threat Model

M16 begins by defining what may be observed, planned, authorized, restored, and verified before any recovery executor exists. This slice is contract-only. It cannot change Source, production, the production pointer, runtime cache, R2 objects, credentials, or the permanent ledger.

## Exact baseline

- Engine: `16dfe909b22d9fbe04fbbb5ddfad49e4341ac3b8`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Every incident and recovery artifact carries these identities. A governed-production plan is invalid when its expected Source or pointer precondition differs from the artifact identity.

## Assets and trust boundaries

The closed asset set covers canonical Source, Engine code, production release and pointer, R2 objects, runtime cache, approvals, the permanent ledger, credentials, and the control plane.

The closed trust boundaries are Source control, CI/CD, control plane, object storage, runtime, operator interface, and evidence store. Evidence uses bounded codes rather than raw payloads or arbitrary exception text.

## Threat baseline

The deterministic baseline includes:

- audience-boundary bypass;
- bad release promotion;
- control-plane loss;
- credential exposure;
- production-operation replay;
- R2 object loss;
- Source history corruption;
- unauthorized pointer change.

Each scenario binds one actor, asset, trust boundary, incident kind, likelihood, impact, source audience, evidence audience, and explicit controls. Evidence audience may become narrower, but it cannot become broader than the Source audience.

## Drill modes

### Simulation only

Simulation plans may assess, contain, plan, and verify. They cannot contain restore, rollback, cache rebuild, Source restore, control-plane reconstruction, or credential-rotation actions.

### Isolated environment

Isolated drills may describe recovery actions but must keep `production_scope=false`. They cannot carry production approval IDs, operation IDs, exact production preconditions, or rollback evidence tokens.

### Governed production

M16.1 defines, but does not execute, the governed-production authority envelope. Representing this mode requires all of the following:

- `production_scope=true`;
- approved human authorization;
- bounded approval ID;
- unique operation ID for replay protection;
- exact expected previous pointer SHA-256;
- exact expected Source SHA;
- rollback evidence code.

The expected pointer and Source identities must match the recovery plan identity. Later M16 slices must still provide a reviewed executor and additional acceptance evidence before any production operation is possible.

No default M16.1 drill policy permits governed production. Credential exposure and unauthorized access are simulation-only. Other recovery scenarios are capped at isolated-environment mode.

## Incident lifecycle

The closed lifecycle is:

`detected → triaged → contained → recovery_planned → recovery_authorized → recovering → verifying → resolved`

`blocked` is available whenever evidence, approval, identity, or verification is insufficient. State transitions are represented as evidence artifacts; this slice does not perform transitions in external systems.

## Evidence safety

Security and recovery artifacts reject:

- raw query or raw answer content;
- bearer, Authorization, Cookie, or JWT material;
- credentials or access-key values;
- private excerpts;
- client IP or hostname material;
- traceback or arbitrary exception text;
- HTTP, file, S3, or R2 URIs;
- unknown extra fields.

Collections are bounded, IDs are closed-format codes, timestamps are timezone-aware UTC, scenario and step IDs are unique, ordering is deterministic, and artifacts use canonical JSON plus SHA-256 tamper detection.

## Permanent ledger boundary

Issue #30 remains a permanent append-only evidence ledger. M16.1 never grants ledger append authority and does not add a ledger entry. A later slice may append only when the ledger's own governed contract explicitly requires incident evidence.

## Acceptance boundary

M16.1 is complete only when its adversarial tests, repository CI, R2 lifecycle regression, prior M15 acceptance surfaces, and the dedicated M16 Security Contract Acceptance workflow pass on one unchanged PR head. No production drill or recovery mutation is part of this slice.
