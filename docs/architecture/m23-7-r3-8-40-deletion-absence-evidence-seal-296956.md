# M23.7 R3.8.40 Deletion/Absence Evidence Seal for Run 29695654053

This seal binds governed deletion run `29694753814` and post-delete schema-v2 Recovery Probe run `29695654053` for diagnostic Worker `knowledge-engine-r3-8-29667556969`.

The deletion workflow used exact authorization PR #946 at merge SHA `343b1a994eba3dea7efd37b9ca3348fc563ae50a`. Its artifact records `worker_delete_dispatched: true` and then failed closed with `delete_cloudflare_error_code` before an inline absence probe. The independent post-delete Recovery Probe subsequently read the official Cloudflare versions and deployments collections and proved `worker_absent`: both collections returned HTTP 404 with code `10007`, zero identities, and state `absent`.

The deletion artifact ZIP SHA-256 is `716855410b4da936b2e3016c15845518ad945450887d3f115ff762a24c67ee0c`. The post-delete recovery artifact ZIP SHA-256 is `03851d8f9d5879346a100299d55cadea1c513b632adc8c7c59862815e34ca187`. The deterministic seal digest is `e8f7717c60ed1a97627af238cd04e4abf9d744228332372d92882adcff512b9c`.

This seal authorizes evidence recording only. It does not authorize deletion replay, Worker deployment, secret or route mutation, Qdrant/R2/source mutation, fresh observation, blocker clearance, promotion, parent closure, or M23.7 closure. Production retrieval remains lexical and both blockers remain retained pending independent cleanup reconciliation.
