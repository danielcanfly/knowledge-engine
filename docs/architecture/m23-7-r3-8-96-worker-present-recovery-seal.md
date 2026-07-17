# M23.7 R3.8.96 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29582686914` for retained diagnostic Worker `knowledge-engine-r3-8-29582316388`, left by failed fresh R3.8 observation run `29582316388`.

The recovery probe was authorized by PR #795, with effective script authorization merged at exact head `aa7be7d5ab57a435d5024f51f9028d8272d91d59`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `b9497142ad9daf744488e433364d3e2e97b2f1604304e43f2b3263bdbe75b9ff`

The artifact identity is:

- Artifact id: `8407666567`
- Artifact name: `m23-7-r3-8-9-recovery-29582686914`
- Artifact ZIP SHA-256:
  `e3cce83064b256fb6247659dbc23fb223c955b0178300d3c4984be03e6440c16`
- Receipt file SHA-256:
  `63f76a5285c2c058421ad7b980cd1a5efb9af2a39fa17a25dd8552e840df5e1d`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
