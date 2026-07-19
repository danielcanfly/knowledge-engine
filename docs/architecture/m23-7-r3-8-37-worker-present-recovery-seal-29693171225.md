# M23.7 R3.8.37 Worker-Present Recovery Seal for Run 29693171225

This seal binds schema-v2 recovery probe run `29693171225` for diagnostic Worker `knowledge-engine-r3-8-29667556969`.

The accepted recovery adapter chain culminated in PR #940 and exact `main` head `9faa0e300f68f51650bcc469d7b1284e98800e26`. The probe performed only Cloudflare control-plane GET requests for Worker versions and deployments.

Cloudflare reported `worker_present`, with four unique version identities and four unique deployment identities. The retained observation version `d8e7a3c5-1c14-4ae8-8ff1-ea8e6f80afda` is present in the version set. The receipt self-digest is `95cad3e49f8fc925a055d64b9c974340d5f6d5369109d993d9b75c4d7dccf35e`; the artifact ZIP SHA-256 is `8814cc61ef129646f3e70992b193ec8f3c01b9b19e7ee8783b93fe425f3e9e13`.

No observation replay, Worker delete/deploy, secret mutation, route invocation, Qdrant access, R2 access, protected mutation, blocker clearance, promotion, parent closure, or M23.7 closure is authorized by this seal. Production retrieval remains lexical and both retained blockers remain in force.
