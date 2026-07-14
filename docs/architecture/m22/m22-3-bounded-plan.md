# M22.3 Deterministic bounded plan compiler

## Status

M22.3 compiles a bounded, deterministic reasoning plan only after M22.2 has produced a valid `activate` decision. It turns structured planning evidence into a finite, reviewable plan DAG without executing retrieval, graph traversal, model calls, tools, or answer synthesis.

M22.3 is the first milestone allowed to construct a planner artifact. The artifact remains evidence, not runtime authority.

## Exact entry baseline

- Engine main: `531f55371564daa7ccfe5ca5cda89b504464b183`
- M22.1 issue #337, implementation PR #338, and reconciliation PR #339: complete
- M22.2 issue #340, implementation PR #342, and reconciliation PR #343: complete
- Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main: `e5ef644053d34e89c70d2ceb37521e1c59234832`

## Input contract

The input schema is `knowledge-engine-m22-plan-evidence/v1` and contains exactly:

- the complete M22.1 policy;
- the complete M22.2 activation evidence;
- the supplied M22.2 activation decision;
- a structured plan request;
- complete protected-state evidence.

M22.3 recomputes the activation decision and requires byte-equivalent evidence. A modified score, reason, policy identity, feature identity, disposition, or decision hash is rejected.

Planning is permitted only when the recomputed disposition is `activate`. `off`, `direct_only`, and `blocked` cannot construct a plan.

## Governed operations

The planner accepts exactly five operations:

- `compare`;
- `causal_chain`;
- `synthesize`;
- `temporal_sequence`;
- `disambiguate`.

Raw query text is not accepted. The plan request contains bounded concept and evidence-source references instead.

## Reference safety

Concept and evidence-source references:

- must be lowercase governed identifiers;
- may contain only letters, digits, `.`, `_`, `:`, and `-`;
- must be 1 through 128 characters;
- must be unique;
- are sorted before hashing and compilation;
- cannot contain paths, URLs, whitespace, prompts, or arbitrary executor payloads.

`compare` requires at least two concept references. Other operations require at least one. A maximum of 16 concept references and 16 evidence-source references is enforced.

## Plan-request bounds

The request contains:

- operation;
- concept references;
- evidence-source references;
- whether typed-relation expansion is required;
- mandatory verification flag;
- estimated hops;
- estimated steps;
- estimated retrievals;
- estimated model calls;
- estimated total tokens;
- estimated timeout.

Verification cannot be disabled. Causal-chain and temporal-sequence operations require typed-relation expansion.

Every estimate must satisfy three ceilings:

1. the global M22.1 maximum;
2. the selected M22.1 policy budget;
3. the M22.2 activation feature estimate.

A plan cannot silently reserve more work than was used to authorize activation.

## Governed step vocabulary

M22.3 emits only:

- `retrieve_seed_concepts`;
- `expand_typed_relations`;
- `retrieve_supporting_evidence`;
- `compare_concepts`;
- `trace_causal_chain`;
- `assemble_synthesis_inputs`;
- `order_temporal_evidence`;
- `resolve_ambiguity_candidates`;
- `verify_acl_provenance_citations`.

There are no arbitrary tool names, provider identifiers, shell commands, URLs, or executable payloads.

## DAG guarantees

The compiler assigns deterministic IDs such as `step-01` and `step-02`.

- every step ID is unique;
- a dependency may reference only an earlier step;
- the generated plan is acyclic by construction;
- retrieval and model-call reservations are summed and checked;
- step count must fit the request estimate and the global maximum;
- the final step is always `verify_acl_provenance_citations`.

The current compiler emits a linear DAG. Later milestones may add bounded parallelism only if they preserve forward-safe dependencies and deterministic identity.

## Output

The output schema is `knowledge-engine-m22-bounded-plan/v1` and contains:

- operation;
- M22.1 policy SHA-256;
- M22.2 activation-decision SHA-256;
- normalized request SHA-256;
- final plan SHA-256;
- ordered plan steps;
- exact budget reservation;
- `planner_constructed: true`;
- `planner_invocations: 1`;
- `execution_started: false`;
- `model_call_count: 0`;
- `production_authority: false`.

`planner_constructed` means a deterministic plan artifact was compiled. It does not mean any plan step ran.

## Determinism

The plan identity binds:

- operation;
- exact M22.1 policy identity;
- exact M22.2 decision identity;
- normalized request identity;
- ordered step bodies and dependencies;
- exact budget reservation.

Identical evidence produces byte-equivalent output. Changes to concept references, evidence references, estimates, operation, activation evidence, or policy change the relevant hash.

## Safety boundaries

M22.3 preserves all earlier boundaries:

- ACL and audience constraints remain mandatory;
- provenance and citations remain mandatory;
- deterministic replay and fallback remain mandatory;
- Graph Neural Retrieval remains forbidden;
- Source write authority remains forbidden;
- production authority remains forbidden;
- all protected mutations remain false.

## Acceptance

M22.3 is accepted only when:

1. M22.1 and M22.2 remain complete and reconciled;
2. the activation decision is recomputed and tamper checked;
3. only `activate` may construct a plan;
4. all five governed operations compile deterministically;
5. all step types come from the closed vocabulary;
6. dependencies are forward-safe and acyclic;
7. plan reservations fit global, policy, and activation ceilings;
8. verification is the mandatory final step;
9. raw queries, unsafe references, duplicate references, unknown fields, and protected mutations fail closed;
10. exact-head CI passes on the accepted implementation and reconciliation heads;
11. no plan execution or M22.4 implementation is included.

## Exclusions

No live retrieval, graph traversal, model/provider call, tool call, step execution, retry loop, answer synthesis, Source mutation, production deployment, production pointer, retained R2 object, credentials, permanent ledger, rollback, M22.4 work, or Graph Neural Retrieval is included.

Production mutation dispatched: false.
