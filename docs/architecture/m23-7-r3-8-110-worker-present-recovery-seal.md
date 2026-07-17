# M23.7 R3.8.110 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29587564980` for retained diagnostic Worker `knowledge-engine-r3-8-29587264678`, left by failed fresh R3.8 observation run `29587264678`.

The recovery probe was authorized by PR #809, with effective script authorization merged at exact head `fbbbf2afb6c9f35bc12bd9d4da589bb5e9695157`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `eaadc828b631564e0a51dd434572afde8824851f71a87ed5e0e2d8444bf2ad57`

The artifact identity is:

- Artifact id: `8409646279`
- Artifact name: `m23-7-r3-8-9-recovery-29587564980`
- Artifact ZIP SHA-256:
  `eba774747dbb9d4f9e41c8918112f9ed173e02c5b87ffa5fb588aa285f13c7d4`
- Receipt file SHA-256:
  `308e6a51eb28d19c4849b235031f7d3c84fb82ec4b38a8543b22f85186ea5a9d`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
