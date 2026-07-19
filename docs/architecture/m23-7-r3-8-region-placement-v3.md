# M23.7 R3.8 Region Placement v3

## Trigger

Fresh observation run `29667556969` deployed Worker `knowledge-engine-r3-8-29667556969` but failed closed at `worker_readiness`. No formal Workers AI, Qdrant, quality, or latency measurement began.

## Root cause

The accepted v2 operator used `placement.hostname` against the public Qdrant Cloud cluster endpoint. That endpoint is a load-balanced cluster front door, while Cloudflare documents hostname and host probes as intended for single-homed infrastructure and unsuitable for anycasted or multicasted resources.

Qdrant Cloud endpoints encode provider and region in the hostname. Region placement v3 derives the corresponding Cloudflare region hint only in memory and writes `placement.region` into the transient Wrangler configuration.

Examples:

- `us-east-1-1.aws.cloud.qdrant.io` becomes `aws:us-east-1`
- `europe-west3-0.gcp.cloud.qdrant.io` becomes `gcp:europe-west3`
- `eastus2-0.azure.cloud.qdrant.io` becomes `azure:eastus2`

The raw hostname and derived region are not persisted in receipts or committed configuration.

## Fail-closed boundary

Unsupported provider labels, malformed Qdrant endpoints, invalid regions, non-HTTPS URLs, or non-Qdrant hostnames fail before Worker deployment with a bounded placement error.

## Preserved invariants

- Worker request contract remains `d081ab57a85b4ea813aeb813090b597340b8c3842ff78d7022d38501e6c282ba`.
- Worker internal shadow latency maximum remains 1200 ms.
- Frozen quality metrics, target ranks, strict-zero gates, and read-only Qdrant behavior remain unchanged.
- Production retrieval remains lexical.
- No production, Qdrant write/delete/reindex, R2, pointer, or source mutation is authorized.
- This repair grants no blocker clearance, promotion, parent closure, or M23.7 closure authority.
