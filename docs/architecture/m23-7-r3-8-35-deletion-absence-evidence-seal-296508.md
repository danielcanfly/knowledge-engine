# M23.7 R3.8.35 Deletion/Absence Evidence Seal for Run 29650833651

This seal binds governed deletion run `29650306710` and subsequent read-only
post-delete recovery probe run `29650833651` for diagnostic Worker
`knowledge-engine-r3-8-29646853002`.

Exact deletion authorization PR #930 merged at
`b02b1ef13eddbc9e5dd4abbb978c3e6c7dc402d1` with authorization digest
`8905cf8ea2a1da199ed747d38380ed0cb574cdc5f385fdd73caa77f081f174b3`.

The deletion workflow dispatched deletion of the exact authorized Worker, then
failed closed at `absence_probe` with `delete_absence_not_proven`. The deletion
artifact ZIP SHA-256 is
`c94819f6b10f8b3ef125abb2499753b3d4c238daf207bfb0142db109c9f217f7`.

Post-delete recovery probe `29650833651` subsequently observed
`worker_absent`. Both official Cloudflare versions and deployments collections
returned HTTP 404 with error code `10007`, zero identities, and state `absent`.
The recovery artifact ZIP SHA-256 is
`d71e413f1b0ce0e8803c64693146a1e5861633f8434975cbf21558441d49a9dd`.

The deterministic seal digest is
`565fbfdd2a836477741975c86b45ea03795e919d20e4a0fb3d55780fb7ead110`.

No deletion replay, fresh observation, production retrieval mutation, Qdrant
mutation, R2 mutation, source mutation, blocker clearance, promotion, parent
closure, or M23.7 closure is authorized. Production retrieval remains
`lexical`, and both blockers remain retained.
