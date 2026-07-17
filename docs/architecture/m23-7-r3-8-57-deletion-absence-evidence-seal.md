# M23.7 R3.8.57 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempts and subsequent read-only absence
probes for two retained diagnostic Workers:

- `knowledge-engine-r3-8-29568576968`
- `knowledge-engine-r3-8-29568662778`

Remote-delete runs `29571086720` and `29571331893` each dispatched the Worker
delete and then failed closed at `absence_probe` with
`delete_absence_not_proven`. Their failure receipts record
`worker_delete_dispatched=true` and have self-digests:

- `365b7f9e83ed1f563d0c7be2e4062ca8a74142516dab56582e96d6cbe55361b3`
- `c443632f85d98146adb4b4c480f528920bf04e632519e51d7fd6596e3992b88b`

Post-delete recovery probe runs `29571209577` and `29571434586` then performed
read-only Cloudflare control-plane checks. Versions and deployments both
returned 404/10007 with zero identities for each Worker, yielding
`worker_absent`.

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
