# M23.7 R3.8.123 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29592989012` for retained diagnostic Worker `knowledge-engine-r3-8-29592583765`, left by failed fresh R3.8 observation run `29592583765`.

The recovery probe was authorized by PR #824, merged at exact head `58ead07c67f26baf6a6d9646c9ea08bfc6003b7b`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `b50af580177cbddf57e1a54ee8d42e2a5bae9f0c107cce8cfc09afe8d9763952`

The artifact identity is:

- Artifact id: `8411839765`
- Artifact name: `m23-7-r3-8-9-recovery-29592989012`
- Artifact ZIP SHA-256:
  `95960f9d4cfb0e7540763ba56084a06c79d0986c60a8a65a00e1ea9aeb8f98b3`
- Receipt file SHA-256:
  `71cb148320deaafa157e5c9acf706f0d4bb04d98499fc042090e7792af86e58f`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
