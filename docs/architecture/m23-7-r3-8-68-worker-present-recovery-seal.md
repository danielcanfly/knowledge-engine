# M23.7 R3.8.68 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29574761599` for retained
diagnostic Worker `knowledge-engine-r3-8-29574526665`, left by failed fresh
R3.8 observation run `29574526665`.

The recovery probe was authorized by PR #767, with effective script
authorization merged at exact head `e71b1836f0aa6721c1f00b577dada4cae04b2812`.
The probe performed only official Cloudflare control-plane read requests for
Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and
four unique deployment identities for the retained Worker. The recovery receipt
self-digest is:

- `e83590dbbc24c4bfa4ae056eae91527158036ca73ab8b2347f972f04b000783d`

The artifact identity is:

- Artifact id: `8404555733`
- Artifact name: `m23-7-r3-8-9-recovery-29574761599`
- Artifact ZIP SHA-256:
  `ba554aa46a3e1672c64a79ac73b3fd24e71a06a3a0090aff0e60cecee67e4b06`
- Receipt file SHA-256:
  `608a038ba05ded7a8af51a460c88741000930c945d54c93dfda8fbf4c3057a13`

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created for the
retained Worker.
