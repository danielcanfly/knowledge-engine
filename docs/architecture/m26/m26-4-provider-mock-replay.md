# M26.4 Provider Mock, Replay Contract and Privacy Review

**Issue:** #1068  
**Entry Engine SHA:** `7a5b757a227e3d7bd0dd859181fc44511e003420`  
**Accepted predecessor:** `m26_3_context_compiler_accepted`  
**Target after reconciliation:** `m26_4_provider_mock_replay_privacy_accepted`

## Purpose

M26.4 consumes synthetic M26.3 context packages and produces deterministic provider-mock
replay records. It is still not live generation. It does not call a live provider, use
credentials, bind a real corpus, stream final prose or serve production answers.

## Authority boundary

The stage remains synthetic-only. It may read M26.1, M26.2 and M26.3 synthetic fixtures,
contracts and accepted evidence identities. It may write M26.4 contracts, fixtures,
tests, documentation and candidate evidence. It may not mutate Source, Foundation,
release, production pointer, R2 production, Qdrant, canonical identity, canonical relations,
semantic serving, hybrid serving or production answer serving.

Protected-surface stop line: source, foundation, release, production pointer, R2 production,
Qdrant, semantic/hybrid serving and production answer serving remain forbidden.

## Provider mock contract

The provider mock is a deterministic replay harness, not a model invocation. It consumes:

1. a `safe_for_provider_mock=true` M26.3 context package;
2. the M26.4 provider mock policy;
3. the synthetic benchmark case contract.

It produces either:

- a `mock_draft` or `mock_draft_with_warnings` replay with a non-final synthetic draft,
  citation bindings and a privacy review; or
- an `abstain_replayed` record for unsafe/no-match/insufficient context; or
- a `privacy_blocked` record when the privacy review finds secret-like, credential-like,
  actor-hash or PII-like text.

## Privacy review

The privacy review scans provider-facing input surfaces and mock output surfaces. It blocks
secret-like assignments, bearer/API-key material, private-key markers, actor hashes,
email-like text and phone-like text. The review is fail-closed and digest-bound.

## Citation and replay discipline

Every replay citation must bind to an M26.3 context package citation, selected passage ID and
context manifest digest. Prompt-injection passages remain evidence-only. The mock draft never
treats quoted evidence as instruction, and it is explicitly non-final and non-production.

## Downstream

M26.5 may consume only `safe_for_m26_5=true` provider replay records after M26.4 reconciliation.
That does not authorise live provider calls, verified final answers, production answer serving or
real-corpus binding. M26.5 remains blocked until `m26_4_provider_mock_replay_privacy_accepted`
is recorded by a separate reconciliation PR.

This issue does not authorise live provider calls, credentials, provider SDK integration, networked
model execution, Source, Foundation, release, production pointer, R2 production, Qdrant,
semantic/hybrid serving, production answer serving or canonical identity/relation mutation.
