# M26.7 Answer Presentation and Non-Serving Preview

M26.7 turns accepted M26.6 answer-evaluation packages into deterministic presentation packages for UI and contract validation only.

## Accepted predecessor

M26.7 requires `m26_6_answer_evaluation_refusal_gate_accepted` and binds the M26.6 final main seal `1f2dfbba74d6df91baa946bbac82e343ea81750e`.

## Contract

The presentation layer may render:

- non-serving preview status banners;
- claim identity placeholders;
- citation and binding identity lists;
- warning banners for conflict and prompt-injection quarantine;
- refusal banners for fail-closed outcomes.

It must not render final answer text. Claim content is redacted in the preview package. The preview is a contract object, not user-facing production answer authority.

## Boundary

M26.7 does not authorise live provider calls, credentials, provider SDK integration, networked model execution, real corpus binding, semantic or hybrid production serving, verified final answers, production answer serving, Source mutation, Foundation mutation, release mutation, production pointer mutation, R2 production mutation or Qdrant mutation.

## M26.8 entry

M26.8 remains blocked until a separate reconciliation records `m26_7_answer_presentation_non_serving_preview_accepted`.
