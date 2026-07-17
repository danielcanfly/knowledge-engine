# M23.7 R3.8.71 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic Worker `knowledge-engine-r3-8-29574526665`.

Remote-delete run `29575189577` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
records `worker_delete_dispatched=true` and has self-digest:

- `b46b61f4c8e430f951a28ed59ddd7ef17bae29cf829bd3cca8628d0a8daf24e4`

The deletion artifact identity is:

- Artifact id: `8404726263`
- Artifact name: `m23-7-r3-8-deletion-29575189577`
- Artifact ZIP SHA-256:
  `f110185943ec926c9b4df650be41a333fe0062713d7c07442ee4a08113855aa0`
- Failure file SHA-256:
  `ff2382353b18f640de93c2955689ae69eeabf0cf9231637935f3dec268e528ac`

Post-delete recovery probe run `29575259824` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`. Its recovery receipt
self-digest is:

- `cf22726cb7218a70485fa7e5c4c81b75cefd1d6ec05eccd89c5000606db7d846`

The post-delete recovery artifact identity is:

- Artifact id: `8404746907`
- Artifact name: `m23-7-r3-8-9-recovery-29575259824`
- Artifact ZIP SHA-256:
  `f01ec6da2ebf5c97f62afe2451c207ffe8b542cb35f6b8a6adc1b90324c5b63b`
- Receipt file SHA-256:
  `ecb271c1aba7c3462c0c8ef86e6f2e2768d0c3ceeaffd27730723a11bad456ce`

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
