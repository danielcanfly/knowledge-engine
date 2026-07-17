# M23.7 R3.8.126 Deletion/Absence Evidence Seal for 29595625175

This seal binds deletion run `29596832948` and post-delete recovery probe run `29596921351` for retained diagnostic Worker `knowledge-engine-r3-8-29595625175`.

Deletion was authorized by PR #834 at exact main head `a70bb65aaaa22e0507a0505aafe0762862a9959b`. The deletion workflow dispatched the Worker delete and returned governed exit 23 because its immediate absence probe was not yet proven.

The post-delete recovery probe then observed the Worker as absent through official Cloudflare control-plane reads. Both versions and deployments returned 404 with error code `10007` and zero identities.

This seal does not authorize fresh observation, blocker clearance, parent closure, or M23.7 closure. Production retrieval remains `lexical`.
