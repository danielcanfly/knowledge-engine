# M23.7-R3.3a Real-Evidence Compatibility

## Trigger

The first frozen-evidence R3.3 operator run stopped before any Workers AI or Qdrant call because the evaluator required `pilot-document-vectors.f32` and `semantic-vectors.f32` to be byte-identical.

That requirement was not part of the accepted M23.5 evidence contract. PR #391 previously established that these files may come from independent provider generations.

## Correct vector authority

`pilot-document-vectors.f32` remains the sole source for:

- the 107 payload-v2 candidate points;
- per-row payload/vector binding digests;
- local full-corpus cosine ranking;
- the later isolated candidate Qdrant reingestion proposal.

The semantic artifact is a sidecar and is validated independently for:

- exact artifact identity and metadata self-digest;
- Cloudflare BGE-M3 model, dimension, dtype and normalization contract;
- vector byte length, digest, finiteness and unit norms;
- unique semantic rows and a complete 107-section set;
- section-level concept, language, audience, source path and source digest binding;
- the accepted M20 benchmark-results suite digest when present.

Byte identity between independent provider generations is neither required nor inferred.

## Regression gate

The R3.3a test deliberately supplies different pilot and semantic vector bytes. It requires the loader to accept both valid generations, pass the semantic sidecar to the accepted real-evidence validator, and retain the pilot vectors as the ranking corpus.

## Authority boundary

This hotfix dispatches no Workers AI call, Qdrant read or mutation, R2 or pointer mutation, Source mutation, deployment, semantic serving, threshold change, promotion, or production authority.

Production retrieval remains lexical. `blocked_pending_retrieval_quality` remains active. Issue #487 remains open until a new operator receipt is sealed and independently reconciled.
