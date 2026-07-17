# M23.7 R3.8.89 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29580277257` for retained diagnostic Worker `knowledge-engine-r3-8-29579965754`, left by failed fresh R3.8 observation run `29579965754`.

The recovery probe was authorized by PR #788, with effective script authorization merged at exact head `a68fd023678f792c448a73977fe33cbcfc57082e`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `b75d362eb702ce59cf42e62b2e662c24f05cc09773f50724dd4f299c76ec6874`

The artifact identity is:

- Artifact id: `8406706368`
- Artifact name: `m23-7-r3-8-9-recovery-29580277257`
- Artifact ZIP SHA-256:
  `b722027bdd512813e2598a4e18bfc64dafee8ae83ecdde7a950ce67bc503e979`
- Receipt file SHA-256:
  `b8308d8faa4c2f45bf42b1d67026e57e37ee784b05bd4e06de3c4fa025719ff2`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
