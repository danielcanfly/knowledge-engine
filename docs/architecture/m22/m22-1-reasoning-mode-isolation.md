# M22.1 Reasoning mode and isolation contract

## Status

M22.1 establishes the Phase E control boundary for optional multi-hop reasoning. It defines and validates the `off | auto | force` operating modes without implementing planner activation, planning, model execution, graph traversal, or answer synthesis.

M22.1 is deliberately a safety substrate. M22.2 and later slices may consume this contract, but they must not weaken it.

## Exact entry baseline

- Engine main: `a68dfb177ab1b044d23fe5e8077548392d8aec42`
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M21 closure: complete and reconciled
- M22 work before this issue: none

## Modes

### `off`

`off` is the strongest isolation state.

It requires:

- `enabled: false`;
- zero hop, step, retrieval, model-call, token, and timeout budgets;
- planner permission false;
- model-call permission false;
- gate disposition `direct_only`;
- planner constructed false;
- planner invocation count zero;
- model call count zero.

No planner object may be constructed and no model/provider path may be entered merely to decide that reasoning is disabled.

### `auto`

`auto` enables only the ability to request an activation decision.

M22.1 returns `await_activation_decision` and does not construct a planner. The deterministic activation policy belongs to M22.2.

### `force`

`force` records that a later bounded planner is required.

M22.1 returns `planner_required` but still constructs no planner. Planner implementation and execution belong to later M22 slices.

## Finite execution budget

Enabled modes must provide positive bounded values:

| Field | Maximum |
|---|---:|
| `max_hops` | 4 |
| `max_steps` | 12 |
| `max_retrievals` | 16 |
| `max_model_calls` | 4 |
| `max_total_tokens` | 16,000 |
| `timeout_ms` | 45,000 |

`max_steps` and `max_retrievals` must each be at least `max_hops`. Boolean values are rejected as integers.

M22.1 does not consume the budget. It validates the ceiling that later slices must obey.

## Identity binding

Every policy binds to:

- exact Engine commit SHA;
- exact Source commit `a6ba738d910d01d2ae99b1968f0831989934c549`;
- exact Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832`;
- bounded release ID;
- exact manifest SHA-256;
- audience.

The canonical policy SHA-256 changes when any identity, mode, budget, audience, or boundary changes.

## Mandatory safety boundaries

All modes require:

- ACL enforcement;
- no audience broadening;
- provenance;
- citations;
- deterministic replay;
- capability-preserving fallback.

The following are always forbidden:

- Graph Neural Retrieval;
- Source writes;
- production authority;
- production mutation;
- production pointer update;
- retained R2 creation;
- credential modification;
- permanent-ledger writes;
- rollback dispatch.

Unknown fields fail closed. Provider names, keys, tokens, credentials, network clients, and executor dependencies are outside this contract.

## Deterministic outputs

Successful validation emits `knowledge-engine-m22-reasoning-mode/v1`.

Gate evaluation emits `knowledge-engine-m22-reasoning-gate/v1` with:

- selected mode;
- bounded disposition;
- `planner_constructed: false`;
- `planner_invocations: 0`;
- `model_call_count: 0`;
- policy SHA-256;
- `production_authority: false`.

## Acceptance

M22.1 is accepted only when:

1. M21 closure remains complete;
2. issue, implementation PR, and reconciliation PR are independent;
3. all required CI is green on the exact accepted heads;
4. `off` proves zero planner construction and zero model calls;
5. `auto` and `force` remain non-executing in M22.1;
6. finite budgets reject zero in enabled modes and reject all configured work in `off`;
7. Source and Foundation are exact pinned identities;
8. ACL, provenance, citation, replay, and fallback boundaries are mandatory;
9. Graph Neural Retrieval and every protected mutation remain forbidden;
10. no M22.2 implementation is included.

## Exclusions

No activation heuristic, planner, model/provider call, network request, live retrieval, graph traversal, semantic search, step executor, retry loop, answer synthesis, Source mutation, production deployment, production pointer, retained R2 object, credential, permanent ledger, rollback, or M22.2 work is included.

Production mutation dispatched: false.

## Closure reconciliation

M22.1 implementation was reconciled against live GitHub state.

- issue: #337;
- implementation PR: #338;
- exact entry base: `a68dfb177ab1b044d23fe5e8077548392d8aec42`;
- accepted implementation head: `002b04a68430f4d24c4a4ce2a05ff03a4fd4ece0`;
- implementation merge: `02fa5715fde28eba0b9baa7629ab14dab5e15a61`;
- implementation branch: `feat/m22-1-reasoning-mode-isolation`.

The accepted implementation diff contained exactly:

- `.github/workflows/m22-1-reasoning-mode-isolation.yml`;
- `docs/architecture/m22/m22-1-reasoning-mode-isolation.md`;
- `src/knowledge_engine/m22_reasoning_modes.py`;
- `tests/test_m22_1_reasoning_modes.py`.

The final implementation head passed:

- M22.1 Reasoning Mode Isolation #1;
- CI #708;
- M17 Architecture Canon Acceptance #85;
- M18 Graph v2 acceptance #144;
- R2 Release Integration #479.

The implementation PR had no conversation comments, submitted reviews, or unresolved review threads. It was merged with expected head `002b04a68430f4d24c4a4ce2a05ff03a4fd4ece0`.

Protected-state review confirmed no Source mutation, production mutation, production pointer update, retained R2 creation, credential modification, permanent-ledger write, rollback dispatch, Graph Neural Retrieval, or M22.2 implementation. Production mutation dispatched: false.
