# M23.7 R3.8.82 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29578467800` for retained
diagnostic Worker `knowledge-engine-r3-8-29578234650`, left by failed fresh
R3.8 observation run `29578234650`.

The recovery probe was authorized by PR #781, with effective script
authorization merged at exact head `375957013ea36a11ff286b7d92d39d5ca8ecb879`.
The probe performed only official Cloudflare control-plane read requests for
Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and
four unique deployment identities for the retained Worker. The recovery receipt
self-digest is:

- `ba104a12791c2123643b0a0ae604465438daa0aee1024963bfc1034f02e93c80`

The artifact identity is:

- Artifact id: `8406001532`
- Artifact name: `m23-7-r3-8-9-recovery-29578467800`
- Artifact ZIP SHA-256:
  `f98e5e2a5b6d641d4633c48d2507ee2f418461a198bd452140b907726a4c1ce2`
- Receipt file SHA-256:
  `54b98917b54a8165961c94d88e0c4e1c1c13fb35f31f7adbdb2c6779b35a1927`

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created for the
retained Worker.
