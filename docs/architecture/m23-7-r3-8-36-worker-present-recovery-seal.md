# M23.7 R3.8.36 Worker-Present Recovery Seal

This seal binds schema-v2 recovery probe run `29559298060` for diagnostic worker
`knowledge-engine-r3-8-29558980092`.

The probe was authorized by PR #709 and ran at exact head
`31d463d3874170d029ffd7185f5b842d46ed0d06`. It performed only official
Cloudflare control-plane read requests for Worker versions and deployments.

The worker is present. Cloudflare returned four unique version identities and
four unique deployment identities. The recovery receipt self-digest is
`939994463dd5aba84baf1d35afd01e575224d62652c1bc208b483f832c0196bf`, and the
artifact ZIP SHA-256 is
`b63c089ad97d537a56a4f8b517683fba52e897edcfec0cd02e1c40c885631652`.

No observation was replayed. No worker delete, deploy, secret mutation, route
invocation, Qdrant access, R2 access, protected mutation, blocker clearance, or
closure action occurred. Production retrieval remains `lexical`.

The next legal step is independent reconciliation of this worker-present seal.
Only after that may a separate deletion authorization be created.
