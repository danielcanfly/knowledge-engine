# M23.7-R3.2 Repair Reconciliation

## Accepted implementation

- Issue: `#484`
- Parent issue: `#474`
- Implementation PR: `#485`
- Accepted implementation head: `912baf83793a1e9f15a0b4ba64e7234d8d8aea64`
- Implementation merge: `41199beba5eb9275bfe1378be2d1c1ee3ef5f8f0`
- Repair contract SHA-256: `9ed7a5bea7ce85aed67bf6f263c8b06420e1c67bd7cac62f9368f0f48c29c33e`
- Reconciliation record SHA-256: `254697028341215cec2789e111fe82a7644d86c1bb43cf2839d0668921ecd289`

## Reconciled repair

The accepted implementation restores `section_title` and `language` in payload schema v2, compiles semantic queries from title, concept, structural locator and language, and fails closed on any text-only query identity collision.

The offline ingestion preview binds each validated document, deterministic point ID, semantic payload and exact normalized vector row. It does not dispatch a write.

The embedding model remains `@cf/baai/bge-m3`, dimension 1024, named vector `default`, without a new query prefix. R3.1 did not support an embedding or payload-to-vector mapping defect as causal.

## Accepted exact-head workflows

All workflows below completed successfully at implementation head `912baf83793a1e9f15a0b4ba64e7234d8d8aea64`:

- M23.7 Repair R3.2 Semantic Payload Repair: `29452224713`
- CI: `29452224705`
- M17 Architecture Canon Acceptance: `29452224704`
- M18 Graph v2 acceptance: `29452224700`
- R2 Release Integration: `29452224743`

The global CI also exposed a pre-existing synthetic ZIP timestamp flake. The repair fixes only the M23.6.2 synthetic test fixture by assigning a fixed ZIP member timestamp. Production ingestion digest semantics remain unchanged.

## Authority state

No Qdrant write, delete, reindex, collection recreation, R2 mutation, pointer mutation, Source mutation, deployment, semantic serving or promotion was dispatched.

Production retrieval remains `lexical`. Promotion eligibility remains false. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` remains open.

## Next gate

The next legal workstream is a separately governed offline 107-point payload-v2 rebuild and retrieval evaluation. It must consume frozen source evidence and may generate local candidate artifacts, but any Qdrant write or live re-observation requires new explicit authority.
