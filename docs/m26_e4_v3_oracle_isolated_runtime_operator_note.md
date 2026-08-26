# M26 E4 V3 Oracle Isolated Runtime Operator Note

## Status

`M26_E4_V3_ORACLE_ISOLATED_RUNTIME_READY_FOR_MANUAL_RUN_REPAIR3`

This note is a bounded operator handoff for M26 E4 V3. It does not authorize production pointer mutation, canonical route mutation, E5 execution, homepage promotion, P4/P5 formal qualification, or any rerun of already accepted source work.

## Repair history

### Repair1 context

Run `32988134229` / job `98239079293` reached source identity PASS and binding config PASS, then failed only at the isolated runtime health request:

```text
M26_E4_V3_MISSING_BACKEND_TOKEN_IN_BASE_ENV
```

Repair1 did not change source identity, Qdrant/R2 materialization law, production pointer, canonical route, E5, or the frozen base image. It only changed the isolated launcher behavior:

```text
- remove any previous same-name isolated candidate container before checking host_port, so a failed run does not leave 18187 occupied;
- if the frozen base container lacks M26_QUERY_BACKEND_TOKEN, inject an isolated synthetic localhost-only health token into the candidate env file only;
- if the frozen base container lacks KNOWLEDGE_ENGINE_OWNER_SUBJECT_HASH, inject an isolated synthetic localhost-only owner hash into the candidate env file only;
- record auth_bootstrap without exposing token/hash values;
- verifier must confirm secret_values_exposed=false, base_container_env_mutated=false, candidate_env_only=true, localhost_only=true.
```

### Repair2 context

Run `32988874205` / job `98241453629` reached source identity PASS and binding config PASS, then failed at the HTTP health path:

```text
M26_E4_V3_HEALTH_HTTP_404:{"detail":"Not Found"}
```

Repair2 split HTTP liveness from M26 binding proof and verified M26 binding separately through an in-container, no-answer, no-provider probe.

### Repair3 context

Run `32989417579` / job `98243188563` reached source identity PASS and binding config PASS, then proved the container was running and responding HTTP, but the frozen 520aed image still returned 404 for `/v1/health`:

```text
M26_E4_V3_LIVENESS_NOT_OK:M26_E4_V3_LIVENESS_HTTP_404:{"detail":"Not Found"}
```

Repair3 stops treating any specific HTTP route as a hard liveness law because the frozen runtime image route surface can differ from current `main`. E4_V3 now uses:

```text
1. container running check;
2. route-independent HTTP server reachability check, where a 2xx/3xx/4xx response proves the ASGI server is alive;
3. docker exec route inventory to record the actual frozen app route surface;
4. docker exec binding probe to verify M26 release / manifest / Qdrant / graph compatibility;
5. zero answer endpoint/provider/E5 consumption.
```

The binding probe remains the authoritative E4_V3 identity gate:

```text
docker exec <candidate_container> python -c 'load_production_answer_bundle() + build_production_answer_compatibility_report(...)'
```

This probe must prove the isolated candidate resolves the M26 180-source release, manifest, Qdrant collection, graph counts, and compatibility status without calling `/v1/ask`, answer provider, embedding provider, R2 write, Qdrant write, source mutation, production pointer mutation, or E5.

## Frozen identities

```text
SOURCE_REPO=danielcanfly/knowledge-source
SOURCE_PR=24
SOURCE_HEAD_SHA=a738f20b16f10925c8adfe4d625be8db30fb269c
BLOG_SOURCE_SHA=f5e20062c1400d7320fe2dbecf6409a0a8c910a7
RELEASE_ID=m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440
PACK_SHA256=59012fe3818cc1c1e45bed4812cef19f00075bb644b7e0b5fe3cb3a68e0498f8
SOURCE_COUNT=180
SEMANTIC_POINT_COUNT=4424
LEXICAL_DOCUMENT_COUNT=4424
GRAPH_NODE_COUNT=4457
GRAPH_EDGE_COUNT=8995
QDRANT_COLLECTION=m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440
FROZEN_SEMANTIC_RUNTIME_SHA=520aeddb0566ca0ed1e2b74fa1fea1b7504a5e87
PRODUCTION_PORT=18087
E4_V3_DEFAULT_ISOLATED_PORT=18187
```

## Required order

1. Run and verify **M26 E4 Materialize Source Archive** first.
2. Require terminal marker:

```text
M26_E4_ISOLATED_RUNTIME_MATERIALIZATION_PASS
```

3. Require materialization receipt to show:

```text
release_id=m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440
semantic_point_count=4424
qdrant.collection=m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440
qdrant.final_snapshot.points_count=4424
embedding.provider=cloudflare_workers_ai
embedding.model=@cf/baai/bge-m3
embedding.vector_dimension=1024
embedding.vector_name=default
authority.production_pointer_writes=0
authority.canonical_route_mutations=0
authority.e5_consumed_attempts=0
```

4. Only after E4 materialization PASS, run **M26 E4 V3 Oracle Isolated Runtime** from latest `main`.

Default manual input values:

```text
host_port=18187
candidate_container=m26-e4-v3-oracle-isolated-m26blog-59012fe-520aed
```

5. Require terminal markers:

```text
M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS
M26_E4_V3_ORACLE_ISOLATED_RUNTIME_VERIFICATION_PASS
```

6. Require artifact:

```text
m26-e4-v3-oracle-isolated-runtime
```

Containing:

```text
/tmp/m26-e4-v3-binding.json
/tmp/m26-e4-v3-binding/m26-e4-runtime-bundle-offline-receipt.json
/tmp/m26-e4-v3-oracle-isolated-runtime-receipt.log
/tmp/m26-e4-v3-oracle-isolated-runtime-verification.json
```

## Forbidden actions

Do not do any of the following during E4 or E4 V3:

```text
- Do not use host_port=18087.
- Do not mutate channels/production.json.
- Do not change the canonical public route.
- Do not run E5 before E4 and E4 V3 both pass.
- Do not rerun failed jobs from earlier failed runs because that reuses the old commit. Start a fresh manual workflow run from latest main instead.
- Do not call /v1/ask or /v1/ask/stream during E4 V3.
- Do not treat /v1/health or /api/m26/health as required routes for frozen 520aed liveness.
- Do not rerun Source G7, 156→180 construction, 142 rewrites, frontend/API wiring, old runtime archaeology, offline adapter rebuild, or zero-reembed judgment.
- Do not rebuild the frozen semantic runtime image.
- Do not change source PR #24.
- Do not promote homepage or run formal P4/P5 qualification.
```

## E4 V3 verification gates

The E4 V3 verifier must fail closed unless all of these are true:

```text
receipt.status=M26_E4_V3_ORACLE_ISOLATED_RUNTIME_PASS
receipt.binding.release_id=m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440
receipt.binding.source_head_sha=a738f20b16f10925c8adfe4d625be8db30fb269c
receipt.binding.source_commit_sha=f5e20062c1400d7320fe2dbecf6409a0a8c910a7
receipt.binding.semantic_point_count=4424
receipt.binding.node_count=4457
receipt.binding.edge_count=8995
receipt.endpoint.host=127.0.0.1
receipt.endpoint.host_port != 18087
receipt.endpoint.answer_endpoint_invoked=false
receipt.liveness.status=http_reachable
receipt.liveness.http_status >= 200
receipt.liveness.http_status < 500
receipt.route_inventory.status=M26_E4_V3_ROUTE_INVENTORY_PASS
receipt.route_inventory.route_count > 0
receipt.route_inventory.answer_endpoint_invoked=false
receipt.binding_probe.status=M26_E4_V3_BINDING_PROBE_PASS
receipt.binding_probe.release_id=m26blog-ec79a3cad1d8-59012fe3818c-4260fcb53440
receipt.binding_probe.qdrant_collection=m26_blog_m26blog_ec79a3cad1d8_59012fe3818c_4260fcb53440
receipt.binding_probe.semantic_point_count=4424
receipt.binding_probe.node_count=4457
receipt.binding_probe.edge_count=8995
receipt.binding_probe.compatibility_status=compatible
receipt.binding_probe.authority.production_pointer_writes=0
receipt.binding_probe.authority.canonical_route_mutations=0
receipt.binding_probe.authority.r2_writes=0
receipt.binding_probe.authority.qdrant_writes=0
receipt.binding_probe.authority.embedding_provider_requests=0
receipt.binding_probe.authority.provider_answer_requests=0
receipt.binding_probe.authority.e5_consumed_attempts=0
receipt.auth_bootstrap.secret_values_exposed=false
receipt.auth_bootstrap.base_container_env_mutated=false
receipt.auth_bootstrap.candidate_env_only=true
receipt.auth_bootstrap.localhost_only=true
receipt.authority.production_pointer_writes=0
receipt.authority.canonical_route_mutations=0
receipt.authority.r2_writes=0
receipt.authority.qdrant_writes=0
receipt.authority.embedding_provider_requests=0
receipt.authority.provider_answer_requests=0
receipt.authority.source_repo_mutations=0
receipt.authority.e5_consumed_attempts=0
```

## Terminal return after E4 V3 pass

```text
M26_E4_V3_ORACLE_ISOLATED_RUNTIME_READY_FOR_E5
E4_MATERIALIZATION=PASS
E4_V3_ORACLE_ISOLATED_RUNTIME=PASS
E4_V3_VERIFICATION=PASS
HOST_PORT=18187
PRODUCTION_MUTATION=false
CANONICAL_ROUTE_MUTATION=false
E5_CONSUMED_ATTEMPTS=0
NEXT=E5_ONE_SHOT_6_OF_6_REQUALIFICATION
```

## Terminal return if E4 V3 fails

```text
M26_E4_V3_ORACLE_ISOLATED_RUNTIME_FAIL
```

Include exact failing step, run id, job id, log excerpt, artifact status, observed value, required invariant, and bounded repair instruction. Do not proceed to E5.
