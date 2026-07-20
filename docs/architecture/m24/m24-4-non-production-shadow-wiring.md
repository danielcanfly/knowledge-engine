# M24 Non-Production Shadow Payload Wiring

This implements the next #966 slice after the flagged runtime guard. It wires a
bounded internal runtime path for semantic/hybrid shadow preview without adding
any production serving authority.

`Runtime.query()` remains lexical. The new `query_m24_shadow_preview()` method is
an internal diagnostic entrypoint that requires:

- `M24_RETRIEVAL_REQUESTED_MODE=semantic_shadow` or `hybrid_shadow`;
- `M24_SEMANTIC_HYBRID_IMPLEMENTATION_ENABLED=true`;
- a non-production channel;
- an explicit caller-supplied query vector;
- semantic diagnostic retrieval already enabled on the runtime.

The method validates the M24 gate before executing lexical or vector retrieval.
It then runs the existing vector diagnostic path and attaches only a bounded
`m24_shadow_preview` to the lexical response. The lexical response remains
authoritative.

## Boundary

- production retrieval remains `lexical`;
- public query APIs do not call the shadow path;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- raw query vectors are not serialized into the preview;
- Qdrant, R2, Source, pointer, credential, traffic, and serving mutations remain
  unauthorized.
