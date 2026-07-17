# M23.7 R3.8.41 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29561818934` for diagnostic worker
`knowledge-engine-r3-8-29561411876`.

The probe was authorized by PR #723 and ran at exact head
`8c74bd32234c4346aaf0b4f3ea16f3dccf56831b`. It performed only official
Cloudflare control-plane read requests for Worker versions and deployments.

The worker is present. Cloudflare returned four unique version identities and
four unique deployment identities. The recovery receipt self-digest is
`58987b1b6884eaa5eedf7f7678860bfa1ca08de384ef40e19c1f8d84b98f2af1`, and the
artifact ZIP SHA-256 is
`f2bca79e7cfd317fcb5efd92dceba1686ba8ce51575b1ce1c0453f969c59ed88`.

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created.
