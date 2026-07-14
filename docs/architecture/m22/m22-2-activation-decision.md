# M22.2 Deterministic reasoning activation decision

## Status

M22.2 implements the deterministic, evidence-only decision that determines whether the optional reasoning path should remain direct, request a later bounded planner, or stop because a safety boundary is not satisfied.

M22.2 consumes the M22.1 `off | auto | force` policy. It does not construct a planner, call a model, retrieve data, traverse the graph, or synthesize an answer.

## Exact entry baseline

- Engine main: `5cbf5d9e2871e1ad24ffcc4d5109330c04d9fa5d`
- M22.1 issue: #337 completed
- M22.1 implementation PR: #338 merged
- M22.1 reconciliation PR: #339 merged
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Why activation is deterministic

M22.2 does not ask an LLM whether an LLM-backed planner should run. The decision uses only bounded structured evidence. This avoids hidden routing drift, provider dependence, prompt injection, unbounded cost, and decisions that cannot be replayed.

Raw query text is not accepted by the contract. Upstream systems must emit privacy-safe features.

## Input contract

The input schema is `knowledge-engine-m22-activation-evidence/v1` and contains:

- the complete M22.1 policy;
- structured query features;
- complete protected-state evidence.

The feature object contains exactly:

- concept count;
- relation count;
- comparison required;
- causal chain required;
- synthesis required;
- temporal sequence required;
- ambiguity score from 0 through 100;
- required evidence-source count;
- direct-answer availability;
- not-found state;
- ACL sufficiency;
- estimated hops;
- estimated steps;
- estimated retrievals;
- estimated model calls;
- estimated total tokens;
- estimated timeout.

Unknown fields fail closed. Boolean values cannot masquerade as integer features.

## Global bounds

Features may not exceed the M22.1 ceilings:

| Feature | Maximum |
|---|---:|
| concepts | 16 |
| relations | 32 |
| evidence sources | 16 |
| estimated hops | 4 |
| estimated steps | 12 |
| estimated retrievals | 16 |
| estimated model calls | 4 |
| estimated total tokens | 16,000 |
| estimated timeout | 45,000 ms |

The estimates must also fit inside the selected M22.1 policy budget. A value that is globally legal but above the request policy is blocked.

## Decision order

Safety overrides are evaluated before activation scoring:

1. insufficient ACL evidence produces `blocked`;
2. not-found evidence produces `direct_only`;
3. `off` produces `direct_only`;
4. policy-budget overflow produces `blocked`;
5. `force` produces `activate`;
6. `auto` applies the deterministic scoring rule.

No branch constructs or invokes a planner.

## Auto-mode scoring

The governed activation threshold is 4. Signals contribute:

| Signal | Score |
|---|---:|
| comparison required | +2 |
| causal chain required | +2 |
| synthesis required | +2 |
| temporal sequence required | +1 |
| three or more concepts | +2 |
| exactly two concepts | +1 |
| two or more relations | +2 |
| exactly one relation | +1 |
| three or more evidence sources | +2 |
| exactly two evidence sources | +1 |
| ambiguity score at least 70 | +2 |
| ambiguity score 40 through 69 | +1 |
| estimated hops at least 2 | +2 |
| direct answer available | -3 |

Auto mode activates only when:

- the score is at least 4; and
- estimated hops are at least 2; and
- ACL and budget evidence pass.

A high score without an actual multi-hop estimate remains direct-only.

## Explainability and identity

Every output contains ordered reason codes and three deterministic identities:

- M22.1 policy SHA-256;
- normalized feature SHA-256;
- final decision SHA-256.

The decision identity binds mode, disposition, score, reasons, policy identity, and feature identity. Identical input yields byte-equivalent output.

## Output

The output schema is `knowledge-engine-m22-activation-decision/v1` and contains:

- mode;
- disposition: `direct_only | activate | blocked`;
- score;
- ordered reason codes;
- policy SHA-256;
- feature SHA-256;
- decision SHA-256;
- `planner_constructed: false`;
- `planner_invocations: 0`;
- `model_call_count: 0`;
- `production_authority: false`.

`activate` means only that a later governed slice may construct a bounded planner. It is not execution authority.

## Safety boundaries

M22.2 preserves every M22.1 boundary:

- exact release identity;
- ACL enforcement;
- no audience broadening;
- provenance and citations required;
- deterministic replay;
- fallback required;
- Graph Neural Retrieval forbidden;
- Source writes forbidden;
- production authority forbidden;
- all protected mutations false.

## Acceptance

M22.2 is accepted only when:

1. M22.1 implementation and reconciliation remain complete;
2. issue, implementation PR, and reconciliation PR are independent;
3. all required exact-head workflows are green;
4. `off` never activates;
5. `force` activates only when ACL and budget evidence are valid;
6. simple direct facts remain direct in `auto`;
7. bounded multi-hop comparison and synthesis evidence activates in `auto`;
8. high score without at least two estimated hops remains direct;
9. ACL insufficiency blocks every mode;
10. not-found evidence never activates;
11. budget overflow blocks enabled modes;
12. raw query text and unknown fields are rejected;
13. no planner, provider, network, retrieval, graph traversal, or M22.3 code is included.

## Exclusions

No planner implementation, plan graph, step executor, provider/model call, network request, live retrieval, graph traversal, semantic search, answer synthesis, Source mutation, production deployment, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22.3 work, or Graph Neural Retrieval is included.

Production mutation dispatched: false.
