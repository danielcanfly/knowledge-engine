# M23.7 R3.8.21 Worker-Present Recovery Seal

This seal records the read-only recovery probe for retained diagnostic worker
`knowledge-engine-r3-8-29550965495`.

The recovery probe run was `29551723834`, executed from Engine head
`60d60b0dfb55bdecb9e6cd069cdef75fb097cc8a`, after PR #663 authorized the
additional affected run. The affected failed remote observation remains
`29550965495` at Engine head `e36559665429514789a6a0122d3b7ac8ff4d5765`.

## Evidence

- Artifact: `m23-7-r3-8-9-recovery-29551723834`
- Artifact ID: `8395963532`
- Artifact zip SHA-256:
  `4dc1d2b08d7bd626c9913062cb06b426497ac1977dae909b0592efdcf46ce890`
- Receipt file SHA-256:
  `920d256427c043798a2e38c7b76dc8d12d65e24199031eac98a3354caa0966d6`
- Receipt self digest:
  `b9a16f9bf9f8959e01daf739c821b76a71eea5fdecb7f76ab76d601d6533a3c2`
- Seal SHA-256:
  `308bc22893ff2fbf24ae3b2cf7030e30a9f7f0ade6c16912c42ab5d7510a608a`

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
created for `knowledge-engine-r3-8-29550965495`.
