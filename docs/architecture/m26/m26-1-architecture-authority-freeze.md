# M26.1 Architecture Freeze, Answer Authority and Provider Contract

**Issue:** #1052  
**Entry Engine SHA:** `d68be491f8d07a727bcf1f521a2e5e75256eede3`  
**Accepted predecessor:** `m25_5_identity_governance_accepted`  
**Target after independent reconciliation:** `m26_1_architecture_authority_accepted`

## ADR-M26-001: Grounded Answer Control Plane

Status: implementation candidate. This document freezes architecture only. It does not enable an Ask runtime, provider call, semantic or hybrid retrieval, or production answer serving.

## Context

The accepted product can perform release-pinned lexical retrieval, bounded typed Graph v2 expansion, Concept Wiki navigation, source viewing and citation drill-in. Those capabilities are evidence-discovery and display surfaces. They do not make model-generated prose authoritative.

M26 therefore separates evidence authority, draft generation and final verification. A citation-bearing draft is not a final answer merely because citations are present. Material claims must be checked against exact authorised passages before release.

## Decision

M26 uses four planes.

### 1. Canonical authority plane

Canonical Source, Foundation, accepted release manifests, immutable `intake/v1` evidence, ACL, licence, audience and provenance identities remain the only factual substrate. M26 is read-only toward this plane.

### 2. Deterministic evidence plane

Question policy invokes existing release-pinned retrieval and bounded Graph v2 expansion. It emits a closed evidence envelope with exact passage, source, section, locator, audience, release and digest identities. This plane performs no provider call and invents no facts.

### 3. Draft generation plane

A provider-neutral adapter receives only an authorised context manifest. It emits a structured draft result. Provider output is untrusted, always marked `draft_only`, and cannot grant factual, canonical, review or serving authority.

### 4. Verification and serving plane

Material claims are extracted and checked against the evidence envelope. Unsupported, contradicted, stale, inaccessible or unverifiable claims are removed, narrowed, qualified, repaired from the same evidence, or cause abstention. Only the final assembler may emit `verified_final`, and only after every hard gate passes.

## Non-negotiable invariants

1. Model confidence never grants authority.
2. Citation presence is not claim support.
3. Cross-release joins fail closed.
4. Every material visible claim maps to authorised passage identities.
5. Graph edges support discovery; a graph edge alone is not prose evidence unless its provenance is included.
6. Context compression may not sever provenance or hide a material contradiction.
7. Provider secrets and raw private content never enter Git, browser payloads, logs or return packages.
8. External browsing and tool calls are disabled by contract.
9. Feedback is an immutable event or governed candidate, never an automatic Source write.
10. All M26 flags are default-off and a global deny overrides every enable.

## Component boundaries

| Component | Reads | Writes | Forbidden |
|---|---|---|---|
| Question policy | authenticated request, release policy | retrieval plan | provider calls, hidden retrieval |
| Retrieval adapter | lexical index, Graph v2, provenance, ACL | evidence envelope | corpus mutation, invented evidence |
| Context compiler | evidence envelope | context manifest | audience broadening, hidden conflict removal |
| Provider adapter | context manifest, provider policy | draft result and usage | finalisation, browsing, tools, canonical writes |
| Claim extractor | draft | material claim set | support approval |
| Verifier | claims and evidence | verdicts and repair plan | new evidence invention |
| Final assembler | verified claims | final answer | unsupported claim release |
| Ask surface | verified answer events | feedback event | provider secrets, restricted evidence exposure |

## Answer authority matrix

| Actor or artifact | Authority | Permitted | Hard boundary |
|---|---|---|---|
| Canonical Source and accepted release | factual authority | read-only use | sole editable truth remains Source governance |
| Immutable intake evidence | evidence authority | exact reference | ACL and licence remain binding |
| Retrieval orchestrator | selection authority | select and rank evidence | cannot assert facts beyond evidence |
| Context compiler | presentation authority | select, deduplicate, order | cannot broaden audience or hide conflicts |
| Provider/model | none | draft generation only | cannot finalise or approve support |
| Claim extractor | classification only | identify material claims | cannot validate support |
| Verifier | support-decision authority | support, qualify, reject | cannot invent evidence |
| Final assembler | final release gate | emit verified answer | only after all hard gates pass |
| Feedback pipeline | candidate-only | immutable feedback/candidate | no direct canonical mutation |
| ChatGPT | engineering execution | issue, branch, code, tests, CI, PR | no Daniel authority or protected mutation |
| Codex | conditional runtime executor | local or secret-bearing bounded tasks | no architecture or authority decision |
| Daniel | human authority | provider/privacy/pilot/serving decisions | approval must be explicit and recorded |

## Final-answer rule

A final answer exists only when authentication and policy pass, release identities match, visible evidence passes ACL recheck, every material claim is supported or explicitly qualified, no hidden material contradiction remains, provider/model/config identities are recorded, and cost, timeout and feature gates pass.

Otherwise the system emits a bounded terminal status such as `no_match`, `insufficient_evidence`, `conflicting_evidence`, `refused_policy`, `provider_unavailable` or `temporarily_unavailable`.

## Provider-neutral generation interface

The provider boundary is replaceable and must not leak provider SDK types into retrieval, verification or UI code.

```text
ProviderAdapter.capabilities() -> ProviderCapabilities
ProviderAdapter.validate_policy(request, policy) -> PolicyVerdict
ProviderAdapter.generate(request) -> GenerationResult
ProviderAdapter.stream(request) -> unverified_draft_delta*
ProviderAdapter.cancel(request_id) -> CancellationReceipt
ProviderAdapter.health() -> ProviderHealth
```

M26.1 freezes the contract only. There is no provider implementation or live call.

### Request requirements

A generation request binds request ID, context digest, provider-registry digest, privacy class, structured-output schema, timeout, maximum output tokens, idempotency key, `network_access=false` and `tool_calls=false`. Credentials are references resolved outside persisted request content.

### Result requirements

A generation result records provider, model, snapshot, configuration digest, structured draft, finish reason, measured token usage, measured cost, timings, retries, fallback, redacted provider-request identity and raw-response digest. Authority is always `draft_only`.

### Retry and fallback

Retries are finite, reason-coded and idempotent. Fallback is explicit, ordered, policy-approved and recorded. There is no silent model substitution. Schema-invalid output enters bounded repair or abstention, not an unlimited retry loop.

### Privacy gate

A future live adapter requires Daniel approval for provider, model, maximum data class, retention policy, geographic processing, credential reference and cost ceiling. M26.1 grants none of this authority.

## Answer state machine

Machine form is stored under `answer_state_machine` in `pilot/m26/m26-1-architecture-freeze.json`.

The success spine is adjacent:

```text
received
→ authenticated
→ policy_validated
→ question_normalized
→ retrieval_planned
→ retrieving
→ evidence_envelope_ready
→ context_compiling
→ context_ready
→ generation_authorized
→ generation_started
→ draft_received
→ claims_extracted
→ verifying
→ final_assembled
→ safe_streaming
→ completed
```

Bounded repair is:

```text
verifying → repair_planned → repairing → draft_received
```

The maximum repair count is two. Terminal safety states cannot re-enter the success path. Examples include `rejected_acl`, `no_match`, `insufficient_evidence`, `conflicting_evidence`, `context_budget_exceeded`, `provider_timeout`, `provider_schema_invalid`, `verification_failed`, `citation_mismatch`, `cost_budget_exceeded`, `cancelled` and `internal_error_safe`.

Safe streaming begins only after verification. Provider deltas are never final-answer events.

## Reuse and adapter matrix

| Existing capability | Decision | M26 boundary |
|---|---|---|
| M10 canonical JSON and immutable identity | direct reuse | do not fork hashing or evidence identity |
| M14 public query/search/citation contracts | versioned adapter | reuse source cards and locators; do not reuse composed prose as verified answer |
| M14 retrieval and ACL filtering | direct reuse for M26.2 baseline | release-pinned lexical authority remains unchanged |
| M19 Graph v2 read-only service | direct reuse | bounded expansion with provenance, no graph mutation |
| M21 evidence-span candidate validation | adapter | reuse exact locator discipline, no second evidence system |
| M24 canonical release loader and product surfaces | direct reuse | exact release identity and read-only UI integration |
| M25.2 normalised references | adapter | reference immutable objects; do not copy raw payloads |
| M25.3 provider-neutral replay lessons | versioned adapter | separate extraction provider from answer-generation provider |
| M25.4 annotation/split discipline | methodology reuse | no label leakage; held-out evaluation remains held out |
| M25.5 identity governance | direct reuse | resolved identities remain candidate-only unless canonically adopted |
| Evidence envelope, context manifest, answer verifier | new | M26 control-plane artifacts only |

No parallel Source repository, ingestion stack, identity resolver, evidence-span system, citation system or production pointer is created.

## Threat model

The machine freeze records 24 threats. Critical classes include ACL leakage, prompt injection, secret exfiltration, evidence poisoning, citation fabrication, cross-release joins, cache-scope leakage, automatic canonical writes, telemetry content leakage and premature serving authority.

Required controls include pre- and post-retrieval ACL checks, source text treated as data, secret scanning, exact source/section/locator validation, release digest equality, bounded context and graph expansion, metadata-only telemetry, audience/release/policy cache keys, finite retries, cost caps and default-off gates.

Hard security acceptance requires zero ACL leaks, secret exposures, fabricated citations, invalid released locators, prompt-injection authority escapes, automatic canonical writes and unsupported high-impact claims.

## Feature flags

The following flags are frozen default-off:

- `M26_GLOBAL_OFF=true`
- `M26_ENABLED=false`
- `M26_REAL_CORPUS_ENABLED=false`
- `M26_RETRIEVAL_ENABLED=false`
- `M26_GRAPH_EXPANSION_ENABLED=false`
- `M26_CONTEXT_COMPILER_ENABLED=false`
- `M26_PROVIDER_CALLS_ENABLED=false`
- `M26_GENERATION_ENABLED=false`
- `M26_VERIFICATION_ENABLED=false`
- `M26_REPAIR_ENABLED=false`
- `M26_VERIFIED_STREAMING_ENABLED=false`
- `M26_ASK_UI_ENABLED=false`
- `M26_FEEDBACK_ENABLED=false`
- `M26_PILOT_ENABLED=false`
- `M26_PUBLIC_SERVING_ENABLED=false`
- `M26_SEMANTIC_RETRIEVAL_ENABLED=false`
- `M26_HYBRID_RETRIEVAL_ENABLED=false`
- `M26_PROVIDER_FALLBACK_ENABLED=false`
- `M26_CONTENT_LOGGING_ENABLED=false`

Evaluation order is global deny, accepted stage gate, Daniel authority, server configuration, then request policy. A lower layer cannot override a higher deny.

## Exact baseline

- Engine entry: `d68be491f8d07a727bcf1f521a2e5e75256eede3`
- Source: `acf78596ace8a7366688ccef72b507204d09d9f9`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- Release ID: `20260720T160000Z-46137c97263e`
- Manifest SHA-256: `ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`
- Vault SHA-256: `054f2a349c173d62de0d2e7b575fbb97a46611ac435653eb6c9eca5255272f64`
- Production retrieval remains lexical.

## Acceptance boundary

This implementation may freeze schemas, architecture and synthetic fixtures. It does not call a provider, bind a real Ask corpus, enable semantic/hybrid retrieval, mutate Source/Foundation/release/R2/Qdrant/pointer, or serve answers.

M26.2 is not authorised by implementation merge. A separate post-merge reconciliation must record `m26_1_architecture_authority_accepted` before M26.2 begins.
