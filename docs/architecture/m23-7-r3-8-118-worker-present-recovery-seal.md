# M23.7 R3.8.118 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29590293423` for retained diagnostic Worker `knowledge-engine-r3-8-29589719171`, left by failed fresh R3.8 observation run `29589719171`.

The recovery probe was authorized by PRs #816 and #817, with effective script authorization merged at exact head `ce5f7c08b97069f7cd21792b8aee53b89d5c49fe`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `548bac0618d5f8295794888b9a92a79004ac764fc88fb7308200ade164df71a8`

The artifact identity is:

- Artifact id: `8410760455`
- Artifact name: `m23-7-r3-8-9-recovery-29590293423`
- Artifact ZIP SHA-256:
  `ea258d8908744777f2de74a511a5e242129a24ed165b9dd07e6872e11f018e1a`
- Receipt file SHA-256:
  `ab709f563e7a752c00b3e301b9f5bd286c973123c6e4370cb73b1d6d33bee441`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
