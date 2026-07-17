# M23.7 R3.8.92 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic Worker `knowledge-engine-r3-8-29579965754`.

Remote-delete run `29581204940` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
records `worker_delete_dispatched=true` and has self-digest:

- `7bfaf9cc5291604500c88c3fbb799bd5a91a29e4b20ae9394234b2097be8e401`

Post-delete recovery probe run `29581317244` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
