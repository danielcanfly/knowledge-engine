# M24 Semantic/Hybrid Flagged Runtime

This implements the first #966 runtime slice after #965. It adds a guarded M24
selector around lexical retrieval output without enabling production
semantic/hybrid serving.

The selector defaults to lexical production retrieval. Semantic/hybrid shadow
preview requires an explicit implementation flag and a non-production channel.
Even then, shadow preview is diagnostic only and cannot become
response-authoritative.

## Runtime Boundary

- production retrieval remains `lexical`;
- semantic activation is rejected until `m24_semantic_activation_reconciliation`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- lexical fallback remains available;
- semantic preview may not carry production authority or protected mutations.

This slice does not dispatch Qdrant, R2, Source, pointer, credential, traffic, or
serving mutations. It only shapes already-supplied lexical and optional shadow
results under a fail-closed M24 contract.
