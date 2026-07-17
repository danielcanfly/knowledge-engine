# M23.7 R3.8.39 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic worker `knowledge-engine-r3-8-29558980092`.

Remote-delete run `29560181190` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
records `worker_delete_dispatched=true` and has self-digest
`959178d3fb2605d9755ad93519fbc828d4eab09c168cfbe67e62e95769c032a2`.

Post-delete recovery probe run `29560310407` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
