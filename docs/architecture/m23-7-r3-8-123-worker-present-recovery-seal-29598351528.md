# M23.7 R3.8.123 Worker-Present Recovery Seal for 29597922646

This seal binds schema-v2 recovery probe run `29598351528` for retained diagnostic Worker `knowledge-engine-r3-8-29597922646`, left by failed fresh R3.8 observation run `29597922646`.

The recovery probe was authorized by PR #838, merged at exact head `e2c4275f7e483e7e52d4888b8f00ce1a8d510803`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `a2a47edbce9423b2e4da976478f3efff339dcb499f3272bd642b6126b8f63cb2`

The artifact identity is:

- Artifact id: `8413963543`
- Artifact name: `m23-7-r3-8-9-recovery-29598351528`
- Artifact ZIP SHA-256:
  `8f3451d905df13febaa8991938b07e75e2448b084b9dd2ea2dc34a8f574d6e98`
- Receipt file SHA-256:
  `ecc8ddd806151394576329e007cfc03b290f6c2062f11b7cf96500ae31fd742b`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
