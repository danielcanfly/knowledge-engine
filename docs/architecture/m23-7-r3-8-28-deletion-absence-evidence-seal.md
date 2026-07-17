# M23.7 R3.8.28 Deletion/Absence Evidence Seal

## Worker knowledge-engine-r3-8-29607698618

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic worker `knowledge-engine-r3-8-29607698618`.

Deletion authorization merged in PR #873 at
`de790debf9a7e4a39a39320ef1292b3b79f41f4f`, binding authorization digest
`1d3c6196f52f67021e7efd3a1e8a54620cea1e6252608848586a6dd31c3480df`.

Remote-delete run `29609393351` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
is privacy-safe, records `worker_delete_dispatched=true`, and has self-digest
`2dda7315d40eedfb068bd35ed1b50a02547808f1fcbf776feecf1dac98ab2851`.

Post-delete recovery probe run `29609464264` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`. Its receipt
self-digest is `2c8557e7b675057638512c22394c4f332a3f866b6ec1503a00614bdec347344e`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.

## Worker knowledge-engine-r3-8-29604923286

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic worker `knowledge-engine-r3-8-29604923286`.

Deletion authorization merged in PR #864 at
`6ef597b601694c0f6b50756f29341ee357083540`, binding authorization digest
`d097309f1b6dc3cea071b28ebc02eb0cbbf5dd235e2811172e7f38329b7b3e27`.

Remote-delete run `29606674323` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
is privacy-safe, records `worker_delete_dispatched=true`, and has self-digest
`cd7399d4707a611c5ec8471fb830c7183f60e6146284c4821a540f6ed464f6b8`.

Post-delete recovery probe run `29606750152` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`. Its receipt
self-digest is `6a7cfb146c5378bef527b1e3e8f9df2ae781a61a42bfdff34e119e6bf00f758e`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.

## Worker knowledge-engine-r3-8-29553221650

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
