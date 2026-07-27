# M26.PA.3 Live Provider Execution Gate

Status: `m26_pa_3_live_provider_execution_attempt_3_authorized_pending_main_push`

M26.PA.3 begins only after the independent M26.PA.2 reconciliation merge
`8ed2da47d04f6410e55d5855d78f734341aecf2e` and accepted PA.2 status
`m26_pa_2_real_corpus_retrieval_binding_accepted`.

## Provider Decision

Daniel selected MiniMax M3 with credential name `MINIMAX_API_KEY` on 2026-07-27,
refreshed that key on 2026-07-28 after attempt 1 failed with `invalid_api_key`, and
then refreshed the `m23-r3-diagnostic` GitHub environment secret again after attempt 2
failed with HTTP `402` while Daniel confirmed the MiniMax account balance and short-window
usage remained available. This gate records the conservative operating defaults recommended
for attempt 3:

- Provider: `minimax`
- Model: `MiniMax-M3`
- API style: Anthropic-compatible messages
- Endpoint: `https://api.minimax.io/anthropic/v1/messages`
- Live call count: `1` for attempt 3
- Max spend cap: `0.05` USD
- Max output tokens: `256`
- Streaming: disabled
- Thinking parameter: not requested

## Payload Boundary

The attempt 3 live call is a smoke check, not answer generation. It sends only production
metadata identities already accepted by PA.2: release id, manifest digest, pointer digest,
Qdrant collection name, observed point count, deterministic sample digest, and PA.2 receipt
identity. It sends no raw corpus text, no vectors, no user query, and no secret values.

The provider is instructed to return compact JSON acknowledging the bounded gate. The output
is not a production answer, not a verified final answer, and not public-serving evidence.

## Receipt Boundary

The live workflow persists a receipt artifact with request payload hash, response JSON hash,
response text hash, provider response id, model, stop reason, and token usage. It does not
persist the full provider response text and does not persist secret values.

Attempt 1 is immutable failed evidence: run `30271818416`, head
`44bbe10117803fae71abb5072a270b0b213a259a`, HTTP `401`, failure class
`invalid_api_key`, no successful receipt artifact. It is not rerun by this gate.

Attempt 2 is immutable failed evidence: run `30287306002`, head
`8f46de92e1f5ad9b04e38bda508410d092fda97b`, HTTP `402`, failure class
`provider_http_402_after_secret_refresh`, no successful receipt artifact. It is not rerun
by this gate.

The workflow runs the live provider job only on a `main` push whose commit message contains
`[m26.pa3-provider-authorized-attempt-3]`. Pull requests run static validation only.

## Still Forbidden

Production answer serving, public shadow traffic, canary traffic, production pointer
mutation, R2 writes, Qdrant writes, Source mutation, Foundation mutation, release mutation,
verified final answers, raw text persistence, vector transmission, and secret persistence
remain forbidden by this gate.
