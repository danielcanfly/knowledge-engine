---
review-package-schema: m8-source-review-package/v1
batch-id: m8-001-agent-execution-paths
review-status: pending_human_review
target-path: bundle/concepts/agent-execution-paths.md
proposed-x-kos-id: ko_7FHJFQQ11PKPEWC4W25CCBCGZM
proposed-audience: public
proposed-confidence: 0.9
origin-repository: huaihsuanbusiness/daniel-blog
origin-commit: 27e2fe996f878f2129bf510d6a326c02f7d87be5
origin-path: src/content/blog/the-atlas-of-agent-design-patterns-part-2/en.md
origin-blob-sha: 9b8912a4dc0193c0c478bcfe83dfaccff21b7ffe
citation-url: https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-2/
---
# Agent execution paths

An agent system's execution path defines how work moves from an initial condition to a terminal outcome. It is separate from the decision logic inside an individual node. A state machine may control the outer workflow while one state uses bounded ReAct, and a fixed pipeline may contain a planning stage. Architecture reviews should therefore name both the outer execution structure and the node-level decision method instead of forcing the whole system under one label.

## Five primary structures

### Direct

A direct path uses one bounded operation when the information, tools, and output contract are already known. It may still include input validation, one predetermined tool call, an output schema, policy checks, timeouts, and deterministic post-processing.

Direct is the strongest baseline when a single operation can solve the task because it minimizes moving parts, latency, cost, and failure ambiguity. Adding planners, critics, or loops to a bounded transformation should require evidence that they improve quality enough to justify the larger failure surface.

### Pipeline

A pipeline divides work into a predetermined sequence of stages. Each stage may use a model, rule, database, or tool, but the application owns the main route.

A production pipeline should give every stage an explicit input contract, output contract, timeout, error type, and observable result. Optional guarded stages and bounded retries can still fit a pipeline. When waiting, resumability, conditional transitions, and several terminal outcomes become central, the design is better represented as a stateful workflow or state machine.

### Router

A router selects one or more downstream paths based on task type, source of truth, permissions, sensitivity, latency, cost, risk, required tools, language, tenant, or multiple intents. It does not need to solve the request itself.

Routers may be deterministic, model-based, semantic, or hybrid. Hard permission and safety rules should run before uncertain model decisions. A production router also needs explicit abstention outcomes such as unknown, ambiguous, unsupported, clarification required, or human review. Overrides must be permission-controlled and logged with the selected route, policy version, confidence or decision basis, rejected alternatives, fallback, and risk checks.

### State machine

A state machine represents named states and legal transitions selected by guards or conditions. It makes current progress, persisted data, retry limits, waiting states, and terminal outcomes explicit.

Useful terminal outcomes extend beyond success and failure and may include cancelled, partial, expired, or manual resolution required. State machines support bounded recovery, pause and resume, checkpointing, and auditable approvals. A state diagram alone does not guarantee durability or exactly-once effects; those properties depend on persistence, task design, idempotency, and the execution runtime.

### Directed acyclic graph

A DAG represents tasks and directional dependencies without cycles inside one run. Its defining property is dependency, not parallelism or multi-agent organization.

Independent branches may run concurrently when resources allow, but concurrency must be bounded by rate limits, connection pools, model quotas, browser capacity, memory, and cost budgets. Join logic is part of the design: it must define whether all branches are required, whether partial results are acceptable, how timeouts and duplicates are handled, how conflicting evidence is resolved, how provenance is preserved, and whether one failed branch cancels the run.

Retries of a node do not create a semantic graph cycle. Replanning loops usually require an outer state machine, a new DAG run, or another cyclic controller.

## Cross-cutting control layers

### Event-driven execution

Event-driven execution defines what starts work and how messages move between producers and consumers. An event may trigger a direct handler, pipeline, state machine, or DAG.

Production events need stable identity, source, type, and trace context. Because distributed delivery is often at least once, side-effecting consumers need idempotency. Designs should also cover out-of-order and late events, poison messages, dead-letter handling, schema evolution, correlation identifiers, backpressure, and replay.

### Human-in-the-loop

Human-in-the-loop is a governed pause and resume point, not a separate reasoning method or topology. It is appropriate for irreversible actions, permission escalation, public publication, financial or destructive operations, production changes, conflicting evidence, policy exceptions, and decisions that remain human-owned.

The reviewer should see the proposed action, supporting evidence, expected impact, risk, reversibility, editable fields, and consequences of approval or rejection. The workflow must persist enough state to resume without repeating earlier side effects and must define edit, reject, timeout, expiry, escalation, and cancellation behavior.

## Related structures and techniques

Behavior trees organize reusable control and action nodes hierarchically. They are useful for modular, reactive behavior, while state machines may be easier for mixed engineering and operations teams to inspect.

Program generation is an execution technique rather than a peer topology. A model may generate SQL, code, commands, API calls, a DSL, or a workflow definition, but the generated artifact still executes through a direct path, pipeline, state machine, DAG, or combination. Safe execution requires parsing, policy checks, sandboxing, least privilege, allowlists, secret isolation, resource limits, output limits, and tests.

## Selection sequence

Use the smallest structure that satisfies the control requirements:

1. Add an event envelope when external events trigger the work.
2. Insert a human or policy gate before high-impact actions.
3. Start with Direct when one bounded operation is enough.
4. Add a Router when requests need different capabilities or sources of truth.
5. Use a Pipeline when stages are known and stable.
6. Use a State Machine when execution needs persisted states, waits, loops, recovery, approvals, or multiple terminal outcomes.
7. Use a DAG when the work is naturally expressed as directional dependencies with fan-out and join.

These choices are composable. A router may start a state machine, one state may launch a DAG, and an output pipeline may format the final result.

## Controls shared by every structure

Every execution structure should define:

- trace and correlation identifiers;
- persisted state when interruption or recovery is possible;
- typed retryable, permanent, policy, and user errors;
- timeout and cancellation behavior;
- bounded retry with backoff;
- idempotency for side effects;
- fallback and escalation rules;
- cost, token, tool, and concurrency budgets;
- permission and data-access checks;
- provenance and citation preservation;
- terminal outcomes and completion criteria;
- observability at the stage or transition where failure occurs.

The best execution path is not the diagram with the most nodes. It is the smallest reviewable control structure that produces the required result, exposes failure clearly, and recovers without repeating unsafe effects.
