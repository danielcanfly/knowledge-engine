# M23.7 R3.8.123 Worker-Present Recovery Seal for 29600412694

This seal binds schema-v2 recovery probe run `29600907404` for retained diagnostic Worker `knowledge-engine-r3-8-29600412694`, left by failed fresh R3.8 observation run `29600412694`.

The recovery probe was authorized by PR #845, merged at exact head `5d61d378f0965b2803e8bd73d7fb75fb7d067fe9`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `df2ab8d6d854ea55a64943d4ed6849a5a5358455603526683ce66ff70fc8baeb`

The artifact identity is:

- Artifact id: `8414955839`
- Artifact name: `m23-7-r3-8-9-recovery-29600907404`
- Artifact ZIP SHA-256:
  `b1ae363611c642e31fde8d07b6e8b48529bfb921e60925f7d2f1d6a32fab065e`
- Receipt file SHA-256:
  `b61d3cba0fa9a3e3091361a9ff374c806e36f36776331cd743c6530c596a18a9`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
