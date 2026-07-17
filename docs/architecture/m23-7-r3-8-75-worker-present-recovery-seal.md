# M23.7 R3.8.75 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29576499744` for retained
diagnostic Worker `knowledge-engine-r3-8-29576200306`, left by failed fresh
R3.8 observation run `29576200306`.

The recovery probe was authorized by PR #774, with effective script
authorization merged at exact head `4b7bd34af064f61238024f3c2a21afb103b5adf9`.
The probe performed only official Cloudflare control-plane read requests for
Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and
four unique deployment identities for the retained Worker. The recovery receipt
self-digest is:

- `b0f400aed39cb7bf17a31e4b23a84ca5673dbf5d30d3f85d77e2221626a0da86`

The artifact identity is:

- Artifact id: `8405221988`
- Artifact name: `m23-7-r3-8-9-recovery-29576499744`
- Artifact ZIP SHA-256:
  `f6d04bfb81897c7eb3426e7071a5064cf2f3b59d5a56335356a0f8194e1dbd67`
- Receipt file SHA-256:
  `618c943ce88421e581b45fa579957a9a1204e9dbab2f0aea69dd43f4ac155500`

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created for the
retained Worker.
