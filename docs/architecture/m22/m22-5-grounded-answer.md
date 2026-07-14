# M22.5 Deterministic grounded answer and citation package validation

## Status

M22.5 validates a deterministic grounded-answer evidence package built from an exact M22.4 execution trace.

It validates claim identities, citation identities, evidence references, audience, ACL and provenance. It also validates governed fallback when the reasoning trace cannot safely support an answer.

M22.5 does not generate answer text, call a provider, perform a semantic judge evaluation or become a production runtime.

## Exact entry baseline

- Engine main: `0e7e1111fd6c08f3377529b33075a185bfebfcbd`
- M22.1 issue #337, implementation PR #338 and reconciliation PR #339: complete
- M22.2 issue #340, implementation PR #342 and reconciliation PR #343: complete
- M22.3 issue #344, implementation PR #345 and reconciliation PR #346: complete
- M22.4 issue #347, implementation PR #348 and reconciliation PR #349: complete
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Input contract

The input schema is `knowledge-engine-m22-answer-evidence/v1` and contains exactly:

- complete M22.4 execution evidence;
- the supplied M22.4 execution trace;
- an answer candidate;
- complete protected-state evidence.

M22.5 recomputes the execution trace and requires exact equality. A changed trace hash, outcome, step result, usage record or authority field is rejected.

The trace must continue to prove:

- execution evidence was validated;
- the validator did not perform external execution;
- M22.4 did not generate a final answer;
- production authority is false.

## Answer dispositions

M22.5 accepts exactly:

- `answered`;
- `fallback`.

### Answered

An answered package is legal only when the exact M22.4 trace outcome is `completed`.

The package contains:

- a lowercase SHA-256 identity for externally assembled answer content;
- an ordered claim list;
- claim evidence bindings;
- citation records;
- the exact policy audience.

The validator stores hashes and bounded references. It does not receive or generate raw answer text.

### Fallback

A fallback contains no answer SHA-256, claims, citations or claim order.

Governed fallback reasons are:

- `reasoning_failed`;
- `budget_exceeded`;
- `insufficient_evidence`;
- `citation_incomplete`;
- `acl_blocked`;
- `not_found`;
- `direct_answer_preserved`.

A failed trace requires `reasoning_failed`. A budget-stopped trace requires `budget_exceeded`.

A completed trace may still fall back when grounding, citation, ACL or evidence sufficiency cannot be established. `direct_answer_preserved` keeps the capability-preserving direct path explicit.

## Claim contract

Each claim contains exactly:

- sequential claim ID such as `claim-01`;
- claim SHA-256;
- one or more evidence references;
- one or more citation IDs;
- ACL pass;
- provenance completeness;
- support confirmation.

Every claim must be ACL-safe, provenance-complete and supported. Claim evidence must be a subset of output references emitted by completed M22.4 steps.

Claims are bounded to 32 and ordered deterministically. The explicit claim order must exactly match the normalized claim list.

## Citation contract

Each citation contains exactly:

- sequential citation ID such as `citation-01`;
- bounded source reference;
- one or more evidence references;
- exact policy audience;
- ACL pass;
- provenance completeness.

Citation evidence must be a subset of output references emitted by completed M22.4 steps.

Every citation must support at least one claim. Every claim citation ID must exist. Audience broadening or audience mismatch fails closed.

## Deterministic output

The output schema is `knowledge-engine-m22-grounded-answer-package/v1` and contains:

- exact M22.4 trace SHA-256;
- deterministic package SHA-256;
- disposition;
- audience;
- answer SHA-256 or null;
- ordered claims;
- citations;
- fallback reason or null;
- `answer_evidence_validated: true`;
- `answer_content_generated_by_validator: false`;
- `provider_call_performed: false`;
- `production_authority: false`.

The package hash binds the trace identity and the complete normalized candidate.

## Trust boundary

M22.5 validates externally assembled evidence. It does not claim semantic truth merely because a hash exists.

The module contains no:

- answer text;
- prompt;
- provider SDK;
- model invocation;
- network client;
- retriever;
- graph traversal client;
- R2 client;
- shell execution;
- dynamic tool dispatcher;
- A/B evaluator;
- rollout controller.

M22.6 may evaluate behaviour and quality across controlled variants. That work is not pulled into M22.5.

## Safety boundaries

M22.5 preserves:

- exact M22.1 policy and audience identity;
- exact M22.2 activation identity;
- exact M22.3 plan identity;
- exact M22.4 execution-trace identity;
- ACL enforcement;
- no audience broadening;
- claim-level evidence binding;
- citation provenance;
- deterministic replay;
- governed fallback;
- Graph Neural Retrieval forbidden;
- Source writes forbidden;
- production authority forbidden;
- all protected mutations false.

## Acceptance

M22.5 is accepted only when:

1. M22.1 through M22.4 remain complete and reconciled;
2. the execution trace is recomputed and tamper checked;
3. answered packages require a completed trace;
4. every claim binds to completed-step evidence and valid citations;
5. every citation binds to completed-step evidence and exact audience;
6. ACL, provenance and support are complete;
7. IDs and claim order are deterministic and sequential;
8. every citation supports at least one claim;
9. fallback contains no answer material;
10. fallback reason matches the trace outcome;
11. identical evidence produces an identical package hash;
12. exact-head CI passes for implementation and reconciliation;
13. no provider call, answer generation, A/B evaluation or M22.6 implementation is included.

## Exclusions

No answer text generation, semantic LLM judge, provider/model call, network request, live retrieval, production graph traversal, R2 read/write, arbitrary tool execution, A/B evaluation, runtime rollout, Source mutation, production deployment, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22.6 work or Graph Neural Retrieval is included.

Production mutation dispatched: false.
