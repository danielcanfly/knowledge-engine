# M26.3 Context Compiler and Evidence Budgeting

**Issue:** #1064  
**Entry Engine SHA:** `31d6aa093181cb9efbf48d1da70c70ae9181773b`  
**Accepted predecessor:** `m26_2_retrieval_envelope_accepted`  
**Target after reconciliation:** `m26_3_context_compiler_accepted`

## Purpose

M26.3 compiles deterministic, provider-ready context packages from synthetic M26.2 evidence
envelopes. It is still not a generation runtime. It does not call a provider, bind a real corpus,
stream final prose or serve production answers.

## Authority boundary

The stage remains synthetic-only. It may read M26.2 synthetic retrieval outputs, M26.2 policy,
M26.2 benchmark cases and M26.1 schemas. It may write M26.3 contracts, fixtures, tests,
documentation and candidate evidence. It may not mutate Source, Foundation, release, production
pointer, R2 production, Qdrant, canonical identity, canonical relations, semantic serving, hybrid
serving or production answer serving.

## Compiler contract

The compiler consumes:

1. a validated M26.2 evidence envelope;
2. the matching retrieval gap report;
3. the M26.3 context policy.

It produces either:

- a `compiled` or `compiled_with_warnings` context package with a context manifest, evidence budget,
  citation bindings and provider-mock instruction blocks; or
- an `abstain_required` package when the evidence is no-match, insufficient or unsafe for context.

## Evidence budgeting

The compiler reserves instruction tokens, orders passages deterministically by rank and identity,
preserves mandatory conflict passages, records budget exclusions and emits deterministic manifest,
budget and package digests. Budget exclusions do not silently remove accounting; they are written to
the manifest exclusions and evidence budget.

## Security

Prompt-injection phrases remain quoted evidence only. The context system instruction says they must
not be obeyed. Secret-like material and ACL-filtered material are excluded by M26.2 and must not
appear in M26.3 packages. Citation IDs are generated only for selected passage IDs.

## Downstream

M26.4 may consume only `safe_for_provider_mock=true` context packages after M26.3 reconciliation.
That does not authorise live provider calls. M26.4 remains a provider-mock/replay stage unless a later
Daniel gate explicitly grants stronger authority.
