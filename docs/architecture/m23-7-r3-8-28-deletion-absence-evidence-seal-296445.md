# M23.7 R3.8.28 Deletion/Absence Evidence Seal for Run 29644550908

This seal binds the governed deletion attempt and subsequent read-only absence
probe for diagnostic Worker `knowledge-engine-r3-8-29636761264`.

Deletion authorization PR #912 merged at
`37c44eb3f304ecf36e80784b01bd8388c296ec2c` with authorization digest
`f6a7e0c5ef58754aaef5457ad7cbd41d955669d2435153cbcf71c57c129c747f`.

Remote deletion run `29642001997` dispatched deletion of the exact authorized
Worker, then failed closed at `absence_probe` with
`delete_absence_not_proven`. The deletion artifact ZIP SHA-256 is
`37809dc66dcee48905fc5a377ff6f9778dfad9ad41fa44ae68c0ea0885827c58`.

Post-delete recovery probe run `29644550908` subsequently observed
`worker_absent`. Both official Cloudflare control-plane collections returned
HTTP 404 with error code `10007`, zero identities, and state `absent`. The probe
artifact ZIP SHA-256 is
`e82f2ec0047f7c9dc96769af1f97beede0fe6f59574bcfb9028adf29d8c39ec1`.

The deterministic seal digest is
`48ba212c0d14e586879ab05a9812f469962a3f0e41f75b9fc5b008247dcd1968`.

No deletion replay, fresh observation, production retrieval mutation, Qdrant
mutation, R2 mutation, source mutation, blocker clearance, parent closure, or
M23.7 closure is authorized by this seal. Production retrieval remains
`lexical`.

The next legal step is independent deletion reconciliation.
