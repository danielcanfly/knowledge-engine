# M23.7 R3.8.17 Worker-Present Recovery Seal

This seal records the read-only recovery probe for retained diagnostic worker
`knowledge-engine-r3-8-29546336917`.

The recovery probe run was `29546964620`, executed from Engine head
`68451fca29213a836c6b90fa68580cd509ab0d05`, after PR #633 authorized the
additional affected run. The affected failed remote observation remains
`29546336917` at Engine head `b6c60752741b7079d93b25ddbe16a6582f9db966`.

## Evidence

- Artifact: `m23-7-r3-8-9-recovery-29546964620`
- Artifact ID: `8394336348`
- Artifact zip SHA-256:
  `9c08427eeb35bbf6ebc9838c100d30e0d664fb07adce6fd6d92f4ca5b607536f`
- Receipt file SHA-256:
  `4527aeac77d458e30184a0fbf64f05af772f7c36006a02713690619fd7e59c7a`
- Receipt self digest:
  `2262aaf3dacf7d964b7dc07f408aa391b5ab28f977bb7d5a17911221a4b28c55`
- Seal SHA-256:
  `c7c98843d4016aa32c34b5793d7524b8f651c426d20dde104ea7d8795d6d7ca5`

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
created for `knowledge-engine-r3-8-29546336917`.
