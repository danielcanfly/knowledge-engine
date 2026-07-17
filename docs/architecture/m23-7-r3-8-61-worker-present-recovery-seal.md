# M23.7 R3.8.61 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29573139584` for retained
diagnostic Worker `knowledge-engine-r3-8-29572790495`, left by failed fresh
R3.8 observation run `29572790495`.

The recovery probe was authorized by PR #760, with effective script
authorization merged at exact head `154f1c0b32d432c83bd203f0788492c42e4b83ac`.
The probe performed only official Cloudflare control-plane read requests for
Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and
four unique deployment identities for the retained Worker. The recovery receipt
self-digest is:

- `3402c7e570de6182b2c12841c51293eac01524568bcf680a751d98b655dbdb86`

The artifact identity is:

- Artifact id: `8403913216`
- Artifact name: `m23-7-r3-8-9-recovery-29573139584`
- Artifact ZIP SHA-256:
  `975b1797d8e5f031e00bbd2f2e9e10e68daac391b0fdcbc059ec3fbd43337d70`
- Receipt file SHA-256:
  `1e631d68c7785a73923bea520310a384f496a1c125059b7e7b73b61ab929aea0`

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created for the
retained Worker.
