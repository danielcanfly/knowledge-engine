# M23.7 R3.8.121 Deletion/Absence Evidence Seal

This seal binds remote-delete run `29591155342` and post-delete read-only recovery probe `29591288207` for retained diagnostic Worker `knowledge-engine-r3-8-29589719171`.

The deletion workflow dispatched the Worker delete and failed closed at `absence_probe` with `delete_absence_not_proven`. The post-delete recovery probe returned 404/10007 for versions and deployments with zero identities, yielding `worker_absent`.

Seal digest: `9501d6b17e6329200b0ec6a0662be60c3c54f2ac18d7e990583ec4f132c9e7bc`.

This seal authorizes no fresh observation, blocker clearance, parent closure, or M23.7 closure. Production retrieval remains `lexical`.
