# M23.7 R3.8.28 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic worker `knowledge-engine-r3-8-29553221650`.

Deletion authorization merged in PR #687 at
`821d233bd5b902773c3cbe18fd9ab55235afff1e`, binding authorization digest
`174d38fa83cfa9ea7b1df1e859f0e459ab9eacd4e43f53b1b7fe3b543bd22445`.

Remote-delete run `29556646408` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
is privacy-safe, records `worker_delete_dispatched=true`, and has self-digest
`a0f2d5d0bcc90bf5f6717c69d972c16595b941089f47595260b2dd4760a583c8`.

Post-delete recovery probe run `29556712756` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`. Its receipt
self-digest is `1f518380554e7400c59317775f00e3c42f2690a5c00185df8749c721377ff172`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
