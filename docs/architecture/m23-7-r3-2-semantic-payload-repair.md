# M23.7-R3.2 Semantic Payload and Query Compiler Repair

## Governance

This is the separately governed implementation workstream for issue `#484`, under parent `#474`. It begins from the independently reconciled R3.1 merge `011bcf8b019ba9b168c143c45604345b2f2e35e9`.

R3.1 sealed the primary root cause as `identifier_humanisation_query_collision`, with `corpus_hubness` as a compounding factor. The accepted compiler produced eight probe-bound digests but only four text-only query identities.

## Repair decision

The benchmark document already contained `title` and `language`. The v1 ingestion path validated both fields and then discarded them when constructing Qdrant payloads. The query compiler was therefore forced to humanise generic identifiers such as `harness`, `theory`, `part` and `chunk`.

R3.2 repairs that information loss rather than changing the embedding model:

1. Qdrant payload schema v2 adds `section_title` and `language`.
2. Both fields come from the same validated document that is zipped with its vector row.
3. The repaired compiler builds its semantic surface from title, concept, structural locator and language.
4. Every compiled query receives a text-only SHA-256 identity.
5. The compiler fails closed unless all eight text identities are unique.
6. Exact target section binding remains unchanged.

## Embedding and binding disposition

The model remains Cloudflare Workers AI `@cf/baai/bge-m3`, dimension 1024, named vector `default`, L2-normalized with Cosine distance. No query prefix or embedding model change is included because R3.1 found no evidence that either was causal.

The no-write ingestion preview validates every vector dimension and norm, derives the deterministic point ID from `section_id`, builds payload v2 from the corresponding document, and emits a binding digest over row, point, section, text, title, language and vector identity. Payload-to-vector row mapping is revalidated, not redesigned.

## Migration requirement

Existing v1 points cannot be patched safely from their current payloads because the discarded titles are not reconstructible from generic identifiers. A full candidate rebuild from the frozen benchmark/source evidence is required.

This PR does not execute that rebuild against Qdrant. It provides the deterministic compiler, payload builder, point preview and fail-closed tests needed for the next offline rebuild-and-evaluation gate.

## Authority boundary

The following remain false:

- Qdrant write, delete, reindex or collection recreation;
- R2 or production-pointer mutation;
- Source mutation or Source PR merge;
- candidate or production semantic serving;
- deployment and live traffic;
- threshold changes and promotion eligibility.

Production retrieval remains `lexical`. `blocked_pending_retrieval_quality` remains active. Parent issue `#474` remains open.

## Exit

R3.2 closes only after:

1. implementation exact-head CI passes;
2. the implementation PR merges with expected-head protection;
3. an independent reconciliation PR binds the implementation merge and CI runs;
4. issue `#484` closes after reconciliation.

The next legal workstream is an offline 107-point payload-v2 rebuild and retrieval evaluation. Any Qdrant write or live re-observation requires separate authority.
