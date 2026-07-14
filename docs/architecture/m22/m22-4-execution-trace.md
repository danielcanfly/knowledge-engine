# M22.4 Deterministic bounded execution trace validation

## Status

M22.4 validates a complete, deterministic and budget-bounded execution trace for an exact M22.3 plan.

It does not execute retrieval, graph traversal, provider calls, model calls, tools or answer synthesis. External adapters may later produce step-result evidence, but this milestone only validates that evidence against the governed plan and budget.

## Exact entry baseline

- Engine main: `4f0bc8ee154d56d7c465194750bda5c6acd5ac65`
- M22.1 issue #337, implementation PR #338 and reconciliation PR #339: complete
- M22.2 issue #340, implementation PR #342 and reconciliation PR #343: complete
- M22.3 issue #344, implementation PR #345 and reconciliation PR #346: complete
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Input contract

The input schema is `knowledge-engine-m22-execution-evidence/v1` and contains exactly:

- the complete M22.3 planning evidence;
- the supplied M22.3 bounded plan;
- one ordered result for every plan step;
- complete protected-state evidence.

M22.4 recomputes the M22.3 plan and requires exact equality. A changed operation, request, step body, dependency, budget reservation, policy identity, activation identity or plan hash is rejected.

The supplied plan must still prove:

- `planner_constructed: true`;
- `planner_invocations: 1`;
- `execution_started: false`;
- `model_call_count: 0`;
- `production_authority: false`.

These fields prove that the M22.3 artifact was a plan, not an already-executed hidden runtime.

## Step-result contract

Every result is bound to:

- exact plan SHA-256;
- exact step ID;
- exact step type;
- exact input references.

Every result reports:

- status;
- retrievals used;
- model calls used;
- tokens used;
- elapsed milliseconds;
- bounded output references;
- ACL result;
- provenance completeness;
- citation completeness;
- governed error code.

Unknown fields fail closed.

## Governed statuses

M22.4 accepts exactly:

- `completed`;
- `failed`;
- `skipped_budget`;
- `skipped_dependency`.

### Completed

A completed step:

- has no error code;
- passes ACL evidence;
- stays inside its retrieval and model-call reservation;
- includes retrieval evidence when the plan reserved retrieval work.

The final `verify_acl_provenance_citations` step additionally requires complete provenance and citation evidence.

### Failed

A failed step requires a bounded lowercase error code. The validator records the failed step and requires all later steps to be `skipped_dependency`.

### Skipped for budget

A budget-skipped step requires `budget_exceeded`, reports no resource use and causes all later steps to be `skipped_dependency`.

### Skipped for dependency

A dependency-skipped step requires `dependency_not_completed`, reports no resource use and is legal only after an earlier failure or budget stop.

## Resource accounting

M22.4 sums:

- retrievals;
- model calls;
- total tokens;
- elapsed milliseconds.

The totals may not exceed the exact M22.3 budget reservation.

Per-step retrieval and model-call usage may not exceed the corresponding step reservation. Booleans cannot masquerade as integers.

M22.4 rejects traces that claim resource use after a terminal stop or traces whose result count differs from the plan.

## Deterministic output

The output schema is `knowledge-engine-m22-execution-trace/v1` and contains:

- exact plan SHA-256;
- deterministic trace SHA-256;
- outcome;
- stop step and reason where applicable;
- normalized ordered step results;
- aggregate usage;
- `execution_evidence_validated: true`;
- `external_execution_performed_by_validator: false`;
- `final_answer_generated: false`;
- `production_authority: false`.

The trace hash binds the plan identity, outcome, stop state, normalized step evidence and aggregate usage.

## Outcomes

M22.4 emits exactly:

- `completed`;
- `failed`;
- `budget_stopped`.

A completed trace must end with a successful `verify_acl_provenance_citations` step. A trace cannot be marked complete while containing skipped or failed steps.

## Trust boundary

M22.4 validates evidence. It does not trust arbitrary executor claims and does not itself become an executor.

The module contains no:

- network client;
- R2 client;
- production retriever;
- graph traversal client;
- provider SDK;
- model invocation;
- shell execution;
- dynamic tool dispatch;
- answer synthesizer.

Output references are bounded identifiers, not URLs, paths, prompts or executable payloads.

## Safety boundaries

M22.4 preserves all earlier guarantees:

- exact M22.1 policy identity;
- exact M22.2 activation identity;
- exact M22.3 plan identity;
- ACL enforcement;
- no audience broadening;
- provenance and citation verification;
- deterministic replay;
- finite budgets;
- Graph Neural Retrieval forbidden;
- Source writes forbidden;
- production authority forbidden;
- all protected mutations false.

## Acceptance

M22.4 is accepted only when:

1. M22.1 through M22.3 remain complete and reconciled;
2. the bounded plan is recomputed and tamper checked;
3. every plan step has exactly one ordered result;
4. every result matches the exact plan and step identity;
5. per-step and aggregate budgets are enforced;
6. failure and budget stops propagate dependency skips;
7. skipped steps cannot claim resource use or verification;
8. completed steps require ACL evidence;
9. completed traces end with provenance and citation verification;
10. identical evidence produces an identical trace hash;
11. exact-head CI passes for implementation and reconciliation;
12. no external execution, answer synthesis or M22.5 implementation is included.

## Exclusions

No network request, live retrieval, production graph traversal, R2 read/write, provider/model call, arbitrary tool execution, final answer synthesis, retry/refinement loop, Source mutation, production deployment, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22.5 work or Graph Neural Retrieval is included.

Production mutation dispatched: false.
