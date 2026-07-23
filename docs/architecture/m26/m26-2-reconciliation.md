# M26.2 Reconciliation and Acceptance

Status: `m26_2_retrieval_envelope_accepted`

M26.2 entered from exact M26.1 seal `d3cf8cc72d951174f10c0a8328f848143c24e004`, implemented in PR #1059 at exact head `68604fc1d80015ea5706709a1c2eda205bd1feaa`, and merged with expected-head protection as `7507c61f245f1027b1935c8cbcd1826f82d03e52`.

## Accepted result

The accepted retrieval envelope is deterministic, release-pinned, synthetic-only and lexical-authoritative. It reuses M14 retrieval, Graph v2 validation and citation enrichment without creating a parallel index, graph authority, citation authority or raw-source fallback.

Nine benchmark cases pass: direct retrieval, M26.1 compatibility, multi-facet depth, Graph discovery, ACL negative, stale evidence, conflicting evidence, prompt-injection containment and genuine no-match. Evidence passages preserve exact source, concept, section, locator, text digest and snapshot digest identities. Population accounting proves there is no silent exclusion.

## Important repair findings

The implementation chain discovered and closed two failure classes before acceptance:

1. final synthetic fixture edits had invalidated source-content, artifact self and registry digests;
2. corpus-wide M14 ACL counters could misclassify a genuine no-match when unrelated restricted documents existed.

The accepted design now computes query-specific restricted lexical, graph and citation candidates without exposing restricted text. `NO_MATCH` and `NO_AUTHORISED_MATCH` are therefore distinct. Graph paths remain discovery metadata with no factual support authority.

## Quality and latency

All nine benchmark cases pass with zero ACL leakage, zero semantic or hybrid use, zero provider calls and zero real-corpus binding. The exact-head synthetic benchmark completed 100 iterations with observed p95 below 10 ms, far beneath the 250 ms guardrail. The observation is evidence, not a production latency claim.

## Authority boundary

No live provider, credentials, real corpus, semantic or hybrid serving, production answer serving, Source, Foundation, release, production pointer, R2 production, Qdrant, canonical identity or canonical relation mutation occurred.

## Next legal stage

This independent closure authorizes M26.3 Context Compiler and Evidence Budgeting in synthetic-only mode. M26.3 may consume the accepted Retrieval Envelope, but it still cannot call a provider, bind the real corpus or enable production answer serving.
