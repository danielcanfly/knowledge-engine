# M25.1 Component Reuse Matrix

The machine-readable source of truth is `pilot/m25/m25-1-reuse-map.json`.

| Capability family | Decision | M25 treatment |
|---|---|---|
| M10 immutable intake and evidence identities | Reuse / adapter | Keep `intake/v1`; wrap connector differences. |
| M11 evidence, compiler and review contracts | Reuse / extend | Preserve exact source spans and review-only authority. |
| M11 resolution | Adapter | Compatibility and benchmark lane, not a parallel resolver. |
| M21 inventory and batch checkpoint | Extend / reuse | Generalise inventory; retain deterministic plans and resume. |
| M21 extraction, relation and tag packets | Reuse | Preserve candidate-only and Foundation-governed semantics. |
| M21 entity resolution | Versioned adapter | Replace legacy Source pin with an exact verified Source input. |
| M21 Source PR preparation | Versioned adapter | Retain packet logic and add Daniel decision plus stale-head gates. |
| M24 pilot and release evidence | Extend | Scale only after M25.9 and keep production pointer separate. |
| M24.14.6 baseline | Reuse | Pin all M25 stages to the accepted identities. |
| M25 admission control plane | New | Store plans, state and authority references only. |

## No-parallel-stack invariant

No M25 component may introduce a second raw object, snapshot, derivative, candidate, resolver, or
canonical truth format when an accepted contract already exists. A new envelope is allowed only
when it binds existing artifacts and closes a governance gap.
