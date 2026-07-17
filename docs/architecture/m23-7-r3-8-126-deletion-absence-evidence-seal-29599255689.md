# M23.7 R3.8.126 Deletion/Absence Evidence Seal for 29597922646

This seal binds deletion run `29599152325` and post-delete recovery probe run `29599255689` for retained diagnostic Worker `knowledge-engine-r3-8-29597922646`.

Deletion was authorized by PR #841 at exact main head `2e31a332d841fa38dbe03f4fa6c51d93c2106ed3`. The deletion workflow dispatched the Worker delete and returned governed exit 23 because its immediate absence probe was not yet proven.

The post-delete recovery probe then observed the Worker as absent through official Cloudflare control-plane reads. Both versions and deployments returned 404 with error code `10007` and zero identities.

This seal does not authorize fresh observation, blocker clearance, parent closure, or M23.7 closure. Production retrieval remains `lexical`.
