# M25.10 Live Blog Candidate Deployment

Status: `exact_head_review_before_one_time_live_execution`

## Authority

The exact 156-article Daniel blog Source Pack is admitted at `danielcanfly/knowledge-source@5250f8422f4fa08c1f3dc84840dc756850817635`. Daniel authorised candidate embedding, candidate Qdrant write and readback, R2 candidate publication, an Access-protected Worker route, and deployment of the authenticated M24 internal product against the candidate identity.

Production release pointers, public production traffic, Access policy mutation, credential creation, and production Qdrant mutation remain denied.

## Candidate release

The deployment runner reconstructs the admitted corpus from the immutable public upstream commit, then requires the accepted Source admission, inventory, node and edge identities. It builds a document-native candidate release containing:

- 156 immutable Markdown Sources;
- 25 Series or collection nodes;
- 156 Article nodes;
- 4,041 Section nodes;
- 8,525 structural edges;
- 4,197 lexical and semantic retrieval documents;
- complete Source viewer payloads and exact line locators.

## Semantic indexing

Cloudflare Workers AI `@cf/baai/bge-m3` generates normalized 1,024-dimensional embeddings in bounded batches. The runner creates a release-specific Qdrant collection and performs strong, synchronous batched upserts.

Acceptance requires readback of every deterministic point ID with payload and named vector. Each point is compared using a canonical payload digest and a float32 vector fingerprint. The aggregate fingerprint, all 4,197 IDs, the collection vector contract, collection status, and final point count must match.

## Internal runtime

`llm-wiki-m25-blog-candidate-runtime` is routed only under:

`m24-internal.danielcanfly.com/api/m25/*`

It verifies the existing Cloudflare Access JWT and never creates or changes an Access policy. It supports:

- `/api/m25/health`
- `/api/m25/retrieve`
- `/api/m25/query`

The query route embeds the question, retrieves only payloads bound to the exact candidate release, Source commit and admission digest, and produces a source-grounded answer with candidate citations. The answer model is `@cf/meta/llama-3.1-8b-instruct-fast`; semantic embeddings remain BGE-M3.

## Internal product

The existing M24 static application is regenerated with the candidate Source, graph and search artifacts. `/sources` exposes all 156 full snapshots and `/graph` exposes all 4,222 structural nodes. The old M24 deployment ID is captured before deployment.

## Rollback

Any failure after external mutation triggers bounded rollback:

1. restore the previous successful Pages production deployment;
2. delete the M25 candidate Worker and route;
3. delete the candidate Qdrant collection;
4. delete the candidate R2 channel pointer;
5. leave `channels/production.json` byte-identical.

Immutable candidate release objects may remain only when the candidate pointer and runtime are absent; they have no serving authority. The final receipt records all external identities and explicitly states that the production pointer and public production traffic were not mutated.

## Manual authenticated acceptance

No new Access service token is created. Automated verification proves that unauthenticated requests are denied, while Daniel's existing Access session remains the only authorised browser identity for final visual and query acceptance. The live workflow therefore ends in `deployed_awaiting_authenticated_owner_acceptance` until that one owner check is recorded.
