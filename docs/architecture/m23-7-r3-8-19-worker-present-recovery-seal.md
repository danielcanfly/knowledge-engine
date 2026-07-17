# M23.7 R3.8.19 Worker-Present Recovery Seal

This seal records the read-only recovery probe for retained diagnostic worker
`knowledge-engine-r3-8-29548837457`.

The recovery probe run was `29549300979`, executed from Engine head
`755787e3813068f954bf1d2dc0ffcfbe35f7eecd`, after PR #649 authorized the
additional affected run. The affected failed remote observation remains
`29548837457` at Engine head `47e16b4981698fb304af48377b93210e841c72e2`.

## Evidence

- Artifact: `m23-7-r3-8-9-recovery-29549300979`
- Artifact ID: `8395150980`
- Artifact zip SHA-256:
  `d31498108313dec4cb974e7689943c21d3abd377dcc341fff303b071a6d35866`
- Receipt file SHA-256:
  `3ce3711887327bfec91322130d1477a22dca8ef12d8dc46bd29fd0fe13059f7e`
- Receipt self digest:
  `caa9e4c1700add6553a43b1a90f1e4021bfef24b3820a9770458e14fab4856af`
- Seal SHA-256:
  `7e85dd22facfe3051589181e4eacece578f2075af3b4421196bcff60f051a59f`

## Recovery Result

The worker is still present. The probe observed four worker version identities
and four deployment identities through Cloudflare control-plane reads only.

No observation was replayed, no worker route was invoked, and no worker deploy,
worker delete, worker secret, Qdrant, R2, Source, pointer, production retrieval,
or blocker mutation was dispatched.

## Authority

This PR is evidence-seal only. It does not authorize deletion execution,
fresh observation, blocker clearance, parent closure, or M23.7 closure.

The next legal step after this seal merges is an independent reconciliation PR.
Only after that reconciliation may a separate deletion authorization record be
created for `knowledge-engine-r3-8-29548837457`.
