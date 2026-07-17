# M23.7 R3.8.126 Deletion/Absence Evidence Seal

This seal binds remote-delete run `29593810453` and post-delete read-only recovery probe `29593949411` for retained diagnostic Worker `knowledge-engine-r3-8-29592583765`.

The deletion workflow dispatched the Worker delete and failed closed at `absence_probe` with `delete_absence_not_proven`. The post-delete recovery probe returned 404/10007 for versions and deployments with zero identities, yielding `worker_absent`.

Seal digest: `c5a40960c8fdf3b0ad6db6b5bdd53098399306b4e7aa9a828cfa7f567e4b5770`.

This seal authorizes no fresh observation, blocker clearance, parent closure, or M23.7 closure. Production retrieval remains `lexical`.
