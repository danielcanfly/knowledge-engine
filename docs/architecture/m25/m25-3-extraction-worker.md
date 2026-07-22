# M25.3 Automated Evidence-Bound Extraction Worker

**Accepted predecessor:** `m25_2_intake_orchestrator_accepted`
**Entry Engine main:** `cc83a1e6bae1dce45fca50d3fdb515c26a70d0f9`
**Authority:** candidate-only

## Purpose

M25.3 adds a provider-neutral extraction boundary after M25.2 normalization. It does not add a
live provider, credentials, paid calls, Source writes, canonical adoption, or production serving.
The only enabled provider mode is deterministic recorded-response replay.

## Reuse and adaptation

- M25.2 remains the sole source of plan, checkpoint, inventory, and normalized-output references.
- `intake/v1` remains the sole location for raw bytes, snapshots, derivative metadata, and
  normalized source text.
- `m21_extraction_candidates.build_candidate_packet` remains the candidate and evidence-locator
  validator. M25.3 does not create a parallel proposal schema or a second evidence-span system.
- M23 provider identity lessons are reused conceptually, but M23's frozen SHA bindings and
  hard-coded provider workflow are not reused.

## Data flow

1. Load the exact M25.2 plan bundle and require all extractable items to be `normalized`.
2. Resolve exactly one `admission/v1/normalized/...` reference for each normalized item.
3. Verify normalized bytes, derivative metadata, object hashes, item identity, audience, M21 plan
   identity, and M21 checkpoint completion.
4. Scan normalized text for secret-like material. Secret findings fail closed before provider
   invocation. Prompt-injection findings remain warnings because source text is untrusted data.
5. Build a provider request manifest containing only object references, hashes, warning codes,
   prompt identity, model-policy identity, and candidate-policy identity. Source text is passed to
   the provider interface only in memory and is absent from persisted request and receipt artifacts.
6. Execute a bounded provider route. The current registry permits only `recorded_replay` providers.
7. Validate response identity, authority, proposal count, secret-like output, and forbidden
   authority-escalation fields.
8. Enforce candidate, per-input, and evidence-span caps.
9. Pass proposals through the existing M21 candidate builder to validate exact character offsets,
   excerpt SHA-256 values, controlled tags, supported kinds, and candidate-only authority.
10. Persist immutable request, response, candidate packet, contracts, input manifest, and receipt
    under `admission/v1/extraction/`.

## Provider-neutral interface

A provider implements `ExtractionProvider.invoke(request_manifest, inputs)`. The interface separates:

- the safe persisted request manifest, which contains no source text;
- in-memory `ExtractionInput` values, which carry source text and are never logged or persisted by
  the worker;
- the provider response envelope, which remains untrusted until deterministic validation succeeds.

Provider variability is isolated at this interface. The deterministic post-processor and M21
candidate builder do not depend on provider SDKs or network clients.

## Retry and fallback

- At most three provider routes may be configured.
- At most three attempts per provider may be configured.
- Only an explicit transient `ProviderFailure` is retried.
- Permanent provider failures move to the next bounded route.
- Invalid response identity, authority, secret content, or candidate structure fails closed and is
  not silently accepted.
- Attempt evidence contains provider/model identity, attempt number, status, and safe failure code,
  never raw source text or credentials.

## Prompt-injection and secret controls

The frozen prompt contract requires:

- source text treated as untrusted evidence;
- embedded instructions ignored;
- JSON-only candidate output;
- no secret reproduction;
- no approval, canonical authority, Source mutation, tool call, or credential fields.

Known prompt-injection patterns are recorded as codes in the input manifest. Secret-like normalized
input and secret-like provider proposal values fail closed using safe error messages.

## Determinism

For identical M25.2 artifacts, prompt/model/candidate contracts, and a byte-identical recorded
response set, the following are byte-identical:

- input manifest;
- provider request manifest;
- provider response envelope;
- candidate packet;
- extraction receipt.

No wall-clock timestamp is included in these identities.

## Operator commands

```bash
knowledge-m25-extraction prepare \
  --plan-id <m25plan_...> \
  --store-root <filesystem-store> \
  --prompt-contract pilot/m25/m25-3-prompt-contract.json \
  --model-policy pilot/m25/m25-3-model-policy.json \
  --candidate-policy pilot/m25/m25-3-candidate-policy.json \
  --output-dir .artifacts/m25-3

knowledge-m25-extraction replay \
  --plan-id <m25plan_...> \
  --store-root <filesystem-store> \
  --prompt-contract pilot/m25/m25-3-prompt-contract.json \
  --model-policy pilot/m25/m25-3-model-policy.json \
  --candidate-policy pilot/m25/m25-3-candidate-policy.json \
  --recorded-responses <response-set.json> \
  --output-dir .artifacts/m25-3
```

`prepare` emits the deterministic request digest needed to build or select a recorded response.
`replay` performs no network call.

## Protected boundaries

M25.3 does not permit:

- live provider calls or provider SDK imports;
- API keys, credentials, or secret-bearing environment variables;
- direct model writes to Source;
- model output treated as trusted truth;
- Foundation, release, production pointer, R2 production, or Qdrant mutation;
- semantic/hybrid production retrieval or production answer serving;
- raw private source content in persisted request, receipt, logs, or attempt evidence.

A future live-provider adapter requires a separate Daniel authority decision covering provider,
credential use, cost ceiling, and data-processing policy.
