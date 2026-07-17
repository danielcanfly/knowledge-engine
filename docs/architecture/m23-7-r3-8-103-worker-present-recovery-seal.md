# M23.7 R3.8.103 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29585094990` for retained diagnostic Worker `knowledge-engine-r3-8-29584764087`, left by failed fresh R3.8 observation run `29584764087`.

The recovery probe was authorized by PR #802, with effective script authorization merged at exact head `74f3359bb17ca457845c684b353d9bb9f0855c20`. The probe performed only official Cloudflare control-plane read requests for Worker versions and deployments.

The Worker is present. Cloudflare returned four unique version identities and four unique deployment identities for the retained Worker. The recovery receipt self-digest is:

- `3ed02050d849e0deb32f7a32373cd0ee3ae12bb1fc317a76625187762209a568`

The artifact identity is:

- Artifact id: `8408641786`
- Artifact name: `m23-7-r3-8-9-recovery-29585094990`
- Artifact ZIP SHA-256:
  `294c253969be9efedab029ae71c5d2c30373250fbca76cfb2af7bec2386008b8`
- Receipt file SHA-256:
  `2ad93cbcc19e17454da8fb063f5fa6d075e72196f940e8d7d7046d4b24237ba3`

No observation was replayed. No worker delete, deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal. Only after that may a separate deletion authorization be created for the retained Worker.
