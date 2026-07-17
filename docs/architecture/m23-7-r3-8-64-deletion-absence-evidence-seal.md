# M23.7 R3.8.64 Deletion/Absence Evidence Seal

This seal binds the governed deletion attempt and subsequent read-only absence
probe for retained diagnostic Worker `knowledge-engine-r3-8-29572790495`.

Remote-delete run `29573634922` dispatched the Worker delete and then failed
closed at `absence_probe` with `delete_absence_not_proven`. Its failure receipt
records `worker_delete_dispatched=true` and has self-digest:

- `a980407f9254b1aebe54929eb8cafff8e56acf617b268c4c3a91ba9a382ffec2`

The deletion artifact identity is:

- Artifact id: `8404111769`
- Artifact name: `m23-7-r3-8-deletion-29573634922`
- Artifact ZIP SHA-256:
  `794a7d0a6f9cabc280d957af1b60dc6b0df21aa05ba42031ccc394fbd229ffa3`
- Failure file SHA-256:
  `b392471142a486a1863c6a8abc5f8ea42dda29315c1f96845437394d61945526`

Post-delete recovery probe run `29573711532` then performed read-only
Cloudflare control-plane checks. Versions and deployments both returned
404/10007 with zero identities, yielding `worker_absent`. Its recovery receipt
self-digest is:

- `5a29a697b16df3c7532196c671361c6342c94f390cfdbf788d3539b46b278971`

The post-delete recovery artifact identity is:

- Artifact id: `8404132784`
- Artifact name: `m23-7-r3-8-9-recovery-29573711532`
- Artifact ZIP SHA-256:
  `4e14094185e680cb9d33c0f31ca1d3fb9fe3f227d5b73877140ba47b03782dfe`
- Receipt file SHA-256:
  `0b995fd7ed85375fd40f71bc1904d5f743631de4c2355ea91018b7a92605acac`

This seal does not authorize replaying deletion, fresh observation, blocker
clearance, promotion, parent closure, or M23.7 closure. Production retrieval
remains `lexical`; retrieval quality and latency blockers remain retained.

The next legal step is independent reconciliation of this deletion/absence
evidence.
