# M23.7 R3.8.25 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29555974732` for diagnostic worker
`knowledge-engine-r3-8-29553221650`.

The probe was authorized by PR #681 and ran at exact head
`91fdefe2ee82d3113a11dd59c510befc877d5084`. It performed only the official
Cloudflare control-plane read requests for Worker versions and deployments.

The worker is present. Cloudflare returned four unique version identities and
four unique deployment identities. The recovery receipt self-digest is
`09d2bc430b4343bcd5ce03e89a718339336dcd40f8fcabc8022f444c36440ff1`, and the
artifact ZIP SHA-256 is
`bbb6768cc0a74ee4c6487629bbd86fc085d5a76d23ae1f302d16ef8baaed3412`.

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created.
