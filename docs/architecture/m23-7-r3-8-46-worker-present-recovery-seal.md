# M23.7 R3.8.46 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29565032873` for diagnostic worker
`knowledge-engine-r3-8-29564569280`.

The probe was authorized by PR #736 and ran at exact head
`7170e104e4fc5b59b19a19e0f3f770ed986a25f4`. It performed only official
Cloudflare control-plane read requests for Worker versions and deployments.

The worker is present. Cloudflare returned four unique version identities and
four unique deployment identities. The recovery receipt self-digest is
`8576942d225bd82c3efd150c6aac0f93355386ab3c151ff98beff24e9b7cb779`, and the
artifact ZIP SHA-256 is
`2fd87bcabb0ef0046943dca732e190dafc828225e2acd79d426ebfb0b120e6ad`.

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created.
