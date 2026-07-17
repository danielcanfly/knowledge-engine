# M23.7 R3.8.126 Deletion/Absence Evidence Seal for 29600412694

This seal binds deletion run `29601698281` and post-delete recovery probe run `29601782476` for retained diagnostic Worker `knowledge-engine-r3-8-29600412694`.

Deletion was authorized by PR #848 at exact main head `bfb6cfbe28eaddff8b071a82822a2573da7a3d0a`. The deletion workflow dispatched the Worker delete and returned governed exit 23 because its immediate absence probe was not yet proven.

The post-delete recovery probe then observed the Worker as absent through official Cloudflare control-plane reads. Both versions and deployments returned 404 with error code `10007` and zero identities.

This seal does not authorize fresh observation, blocker clearance, parent closure, or M23.7 closure. Production retrieval remains `lexical`.
