# M24 Semantic Promotion Decision

Issue #965 is accepted as a decision gate, not as a serving activation.

The accepted M23.7 R3.8 evidence allows #966 to start guarded implementation
work for semantic/hybrid retrieval, but the implementation must default to
lexical production retrieval and must not enable semantic answer serving,
semantic promotion, production traffic changes, Qdrant/R2/Source/pointer
mutation, or credential rotation.

## Decision

The decision is `accepted_flagged_implementation_only`.

#966 may proceed after this decision lands, but only for flagged implementation
that keeps production retrieval lexical. Production semantic/hybrid serving
remains blocked until a later activation reconciliation explicitly authorizes a
different state.

## Required Implementation Boundary

- default retrieval mode remains `lexical`;
- semantic/hybrid code must default disabled;
- lexical fallback is required;
- semantic results may not become response-authoritative while disabled;
- no raw user query or raw answer retention is authorized;
- no public semantic endpoint is authorized;
- activation requires a new reconciliation.

## Evidence

The decision binds M23.7 R3.8 live pass evidence:

- run `29715599032`;
- artifact ID `8450463481`;
- artifact ZIP SHA-256
  `7f025b28fad8f6574748f58f0de9042cf15c7b93a8fa8070c105a0ba0419311c`;
- evidence seal SHA-256
  `94dad021d947422933fab588b6f0396c249d73516ae27f3533329480edc7e2eb`;
- reconciliation SHA-256
  `cb6b7d1b7213da018dd8466c9c43538d616f24f65ece25ef1c28ec1ac4e3094a`.

## Next Gate

The next gate is `m24_semantic_activation_reconciliation`. It must happen after
#966 implementation review if production semantic/hybrid serving is still
desired.
