# M22.6 Deterministic offline controlled-variant evaluation

## Status

M22.6 evaluates a direct baseline and bounded-reasoning candidate across a deterministic offline case matrix.

Every variant is represented by exact M22.5 answer evidence and a recomputed grounded-answer package. M22.6 applies a structured rubric and produces a non-executing recommendation. It does not use an LLM judge, allocate traffic, deploy, roll out or modify production.

## Exact entry baseline

- Engine main: `2aa77473775abb2b3c6e7260bfc8b59a2c453736`
- M22.1 issue #337, implementation PR #338 and reconciliation PR #339: complete
- M22.2 issue #340, implementation PR #342 and reconciliation PR #343: complete
- M22.3 issue #344, implementation PR #345 and reconciliation PR #346: complete
- M22.4 issue #347, implementation PR #348 and reconciliation PR #349: complete
- M22.5 issue #350, implementation PR #351 and reconciliation PR #352: complete
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Input contract

The input schema is `knowledge-engine-m22-evaluation-evidence/v1` and contains exactly:

- bounded suite ID;
- minimum required quality gain;
- one through 64 ordered evaluation cases;
- complete protected-state evidence.

Each case contains exactly:

- sequential case ID;
- unique bounded case key;
- structured rubric;
- baseline variant;
- candidate variant.

Each variant contains complete M22.5 answer evidence and the supplied grounded-answer package. M22.6 recomputes every package and rejects any changed package identity, trace identity, claim, citation, audience, fallback, usage or authority field.

## Structured rubric

M22.6 does not inspect raw query text or answer text and does not invoke a semantic judge.

Each case rubric defines:

- expected disposition;
- expected fallback reason or null;
- required claim SHA-256 identities;
- forbidden claim SHA-256 identities;
- minimum citation count;
- maximum total tokens;
- maximum model calls;
- maximum elapsed milliseconds.

Required and forbidden claims cannot overlap. A fallback rubric cannot require citations.

## Variant score

Every variant receives a deterministic score out of 100:

- expected disposition: 25;
- expected fallback: 10;
- required claims covered: 25;
- forbidden claims absent: 15;
- citation threshold: 15;
- cost ceiling: 10.

A case passes only when all six conditions pass. A candidate regression exists when a baseline-passing case fails for the candidate or when the candidate score is lower than the baseline score.

M22.5 recomputation remains the authority for ACL, provenance, citation, evidence and audience validation. M22.6 cannot award points around a failed M22.5 package.

## Recommendations

M22.6 emits exactly:

- `promote_candidate`;
- `hold`;
- `reject`.

### Promote candidate

The recommendation is `promote_candidate` only when:

- every candidate case passes;
- no baseline-passing case regresses;
- every per-case cost ceiling passes;
- average candidate quality gain reaches the configured threshold.

This is a review recommendation only. It is not rollout authority.

### Hold

The recommendation is `hold` when the candidate is safe, all cases pass and there is no regression, but the configured quality-gain threshold is not reached.

### Reject

The recommendation is `reject` when any candidate case fails, any regression occurs, a fallback is incorrect, a required claim is absent, a forbidden claim appears, citations are insufficient or a cost ceiling is exceeded.

## Deterministic output

The output schema is `knowledge-engine-m22-offline-evaluation/v1` and contains:

- suite ID;
- evaluation SHA-256;
- normalized case results;
- baseline and candidate average scores;
- quality gain and threshold;
- regression and pass status;
- aggregate token, model-call and elapsed-time usage;
- recommendation and reason codes;
- `evaluation_only: true`;
- `rollout_performed: false`;
- `traffic_changed: false`;
- `production_authority: false`.

The evaluation identity binds the complete normalized cases, aggregate result, recommendation and reason codes.

## Trust boundary

M22.6 validates offline evidence and computes a deterministic comparison. It contains no:

- raw query or answer text;
- semantic LLM judge;
- provider or model call;
- network client;
- retriever;
- graph traversal client;
- R2 client;
- shell execution;
- traffic allocator;
- shadow-traffic controller;
- canary controller;
- deployment or rollout executor.

The word `promote` in `promote_candidate` describes a recommendation label only. No action is dispatched.

## Safety boundaries

M22.6 preserves:

- exact M22.1 policy and audience identity;
- exact M22.2 activation identity;
- exact M22.3 plan identity;
- exact M22.4 execution identity;
- exact M22.5 package identity;
- ACL and audience boundaries;
- claim-level evidence and citation provenance;
- governed fallback;
- deterministic replay;
- Graph Neural Retrieval forbidden;
- Source writes forbidden;
- production authority forbidden;
- all protected mutations false.

## Acceptance

M22.6 is accepted only when:

1. M22.1 through M22.5 remain complete and reconciled;
2. all baseline and candidate packages are recomputed and tamper checked;
3. suite and case identities are bounded, unique and deterministic;
4. only structured rubrics are used;
5. every score and recommendation is deterministic;
6. regressions and cost failures force rejection;
7. insufficient quality gain forces hold;
8. promotion recommendation requires all candidate cases to pass;
9. exact-head CI passes for implementation and reconciliation;
10. no semantic judge, provider call, traffic change, rollout or M22.7 implementation is included.

## Exclusions

No semantic LLM judge, answer generation, provider/model call, network request, live retrieval, production graph traversal, R2 read/write, arbitrary tool execution, traffic allocation, shadow traffic, canary, deployment, rollout, production pointer, retained evidence, permanent ledger, rollback, M22.7 closure work, Source mutation, credentials or Graph Neural Retrieval is included.

Production mutation dispatched: false.

## Closure reconciliation

M22.6 implementation was reconciled against live GitHub state.

- authoritative issue: #353;
- implementation PR: #354;
- exact entry base: `2aa77473775abb2b3c6e7260bfc8b59a2c453736`;
- accepted implementation head: `7edb988fc0bdc4e78df45b23768cf1f12a56ee78`;
- implementation merge: `5fb14d13030b40d92bccfe1fa164e01e639c7202`;
- implementation branch: `feat/m22-6-offline-evaluation`;
- reconciliation branch: `docs/m22-6-reconciliation`.

The accepted implementation diff contains exactly:

- `.github/workflows/m22-6-offline-evaluation.yml`;
- `docs/architecture/m22/m22-6-offline-evaluation.md`;
- `src/knowledge_engine/m22_offline_evaluation.py`;
- `tests/test_m22_6_offline_evaluation.py`.

Local isolated prevalidation completed with 19 focused tests, Ruff and compileall. The local container could not resolve GitHub, so repository exact-head CI remained authoritative for real M22.1 through M22.6 integration.

The accepted implementation head passed:

- M22.6 Offline Controlled Variant Evaluation #1;
- CI #732;
- M17 Architecture Canon Acceptance #98;
- M18 Graph v2 acceptance #168;
- R2 Release Integration #493.

PR #354 had no conversation comments, submitted reviews or unresolved review threads. Its exact four-file diff and head SHA were revalidated immediately before merge. The implementation was merged using expected head `7edb988fc0bdc4e78df45b23768cf1f12a56ee78`.

Protected-state review confirmed no semantic LLM judge, answer generation, provider or model call, network request, live retrieval, production graph traversal, R2 read or write, arbitrary tool execution, traffic allocation, shadow traffic, canary, deployment, rollout, production pointer update, retained evidence creation, credential modification, permanent-ledger write, rollback dispatch, M22.7 closure work, Source mutation or Graph Neural Retrieval.

Production mutation dispatched: false.
