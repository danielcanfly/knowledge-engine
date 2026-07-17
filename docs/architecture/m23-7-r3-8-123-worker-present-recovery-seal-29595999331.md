# M23.7 R3.8.123 Worker-Present Recovery Seal for 29595625175

This seal binds schema-v2 recovery probe run `29595999331` for retained diagnostic Worker `knowledge-engine-r3-8-29595625175`, left by failed fresh R3.8 observation run `29595625175`.

The recovery probe was authorized by PR #831, merged at exact head `a9dd0bc92d4e4e51d312432b6e1f5329c352d7fc`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `4ca8ee3658bb3452e0c2e65737ea6fdec1cbdadbc24d647ca1f370b2580e6a1a`

The artifact identity is:

- Artifact id: `8413029050`
- Artifact name: `m23-7-r3-8-9-recovery-29595999331`
- Artifact ZIP SHA-256:
  `9cbb09df1f1196cc4ebeb12e6ae10cb4f7fec2960bc67e42db69f57b4ad3659b`
- Receipt file SHA-256:
  `7d76e7bb8bb4ce9adb55f787347c4b5f54bff0fa98e83469c1ee450b0e1dccc2`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
