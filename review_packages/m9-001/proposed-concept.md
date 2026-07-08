---
review-package-schema: governed-source-review-package/v1
batch-id: m9-001-agent-planning-strategies
review-status: pending_human_review
target-path: bundle/concepts/agent-planning-strategies.md
proposed-x-kos-id: ko_7T9Q4M2V8J6K3R5C1N0PWHDBXF
proposed-audience: public
proposed-confidence: 0.9
origin-repository: huaihsuanbusiness/daniel-blog
origin-commit: 27e2fe996f878f2129bf510d6a326c02f7d87be5
origin-path: src/content/blog/the-atlas-of-agent-design-patterns-part-3/en.md
origin-blob-sha: 185fa419771942e0737cdefe10c3180505bb3c23
citation-url: https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-3/
---
# Agent decision and planning strategies

An agent system's outer execution structure and its node-level decision strategy are separate architectural layers. A State Machine may control legal progress while one state uses bounded ReAct, a Planner may create work that later executes as a DAG, and a fixed Pipeline may contain a planning or verification stage. Production reviews should name both layers instead of forcing the entire system under one pattern label.

## Fixed decision logic

Fixed decision logic keeps the next step under application control when the sequence is already known. The model may perform work inside a stage, but it does not redesign the workflow.

This is a strong default for stable ingestion, extraction, transformation, validation, approval procedures, and other tasks with repeatable contracts. Its advantages are predictable cost and latency, straightforward tests, explicit permissions, reproducibility, and clear failure attribution.

A fixed flow still needs typed responses for unmodelled conditions. When a required source disappears or a dependency fails, the system should use an approved fallback, mark data unavailable, request missing authority, stop with a typed failure, or escalate. Deterministic control is not an immature design; autonomy should be added only where predetermined rules are genuinely insufficient.

## Bounded ReAct

ReAct-style execution chooses the next local action after observing the result of the previous action. Its useful production form is a closed loop:

1. read the current goal and state;
2. select an allowed action;
3. execute a tool;
4. normalise the observation;
5. update progress;
6. complete, continue, or escalate.

This pattern is useful when the next effective action cannot be known before inspecting a browser, API, file system, debugger, or external documentation.

A raw action-observation loop does not provide reliability by itself. It does not automatically define progress, completion, permissions, budgets, duplicate detection, durable state, recovery, evidence quality, or final acceptance.

### Step contract

A bounded executor should receive:

- one step objective;
- allowed tools and inputs;
- expected output schema;
- completion criteria;
- prohibited actions;
- time, token, tool, and money budgets;
- maximum action and retry counts;
- current progress state;
- escalation policy;
- provenance requirements.

Tool results should be converted into structured observations that record source identity, extracted facts, unresolved requirements, conflicts, retryability, and suggested next action.

After each observation, the controller should produce exactly one operational outcome:

- `complete` when the step contract is satisfied;
- `continue` when another allowed action is justified;
- `escalate` when the executor cannot finish within its authority or budget.

Duplicate queries, URLs, tool calls, parameters, and equivalent actions should be detected so visible activity is not mistaken for progress.

## Plan-and-Execute

Plan-and-Execute creates a global task structure before carrying out individual steps. It is best treated as a pattern family rather than one canonical algorithm.

A useful plan exposes requirements, ordering, dependencies, delegation, expected outputs, and completion state. It is appropriate for long research, multi-document review, migrations, large code changes, comparisons, and other work where omissions or hidden dependencies are costly.

A plan must be executable rather than ceremonial. Each step should include:

- stable step identifier;
- objective;
- required inputs;
- dependencies;
- allowed tools;
- expected structured output;
- observable completion criteria;
- failure policy;
- budget;
- provenance requirements;
- lifecycle status.

A polished plan is still only a proposal. It may omit a requirement, assume unavailable data, violate a precondition, use a forbidden capability, or decompose the wrong problem.

## Plan validation

Validation strength should match task risk.

Natural-language review can detect missing requirements or weak sequencing in low-risk work. Deterministic validation should check required fields, dependency references, acyclic dependencies, allowed tools, budget totals, preconditions, and output schemas.

Simulation or dry runs are appropriate before irreversible actions. When actions, preconditions, effects, and constraints have a formal model, an external planner or solver may provide stronger feasibility guarantees than free-form generation.

Fluent plan generation is not proof that a plan is valid.

## Adaptive planning and replanning

Adaptive planning revises the remaining plan when execution evidence invalidates a material assumption. It should not rewrite the whole plan after every observation.

Valid replan triggers include:

- a critical premise becomes false;
- required data or a capability is unavailable;
- a dependency changes;
- the goal or an authorised constraint changes;
- verification rejects a result;
- remaining budget cannot support the plan;
- repeated local repair fails;
- a new high-priority risk appears.

Use local repair when the objective, dependencies, and later steps remain valid and an approved fallback can satisfy the same contract. Use global replanning when the decomposition, deliverable, constraints, or multiple downstream dependencies must change.

A revised plan should preserve completed work that remains valid. Production systems should record the immutable original goal, current and previous plan versions, replan trigger, plan diff, preserved and invalidated steps, new dependencies, replan count, verifier decision, and approving actor.

## Hierarchical planning

Hierarchical planning decomposes a large goal into subgoals and executable tasks at several levels. It helps isolate context, delegate ownership, manage independent branches, and keep upper levels focused on outcomes rather than tool calls.

Hierarchy also introduces risks: duplicated work, inconsistent assumptions, intent loss during hand-offs, incompatible output formats, and completion of every child task without completion of the parent goal.

A production hierarchy therefore needs parent and child completion contracts, shared terminology and facts, provenance, dependency management, integration ownership, and cross-subgoal verification.

## Hierarchical Task Network planning

Hierarchical Task Network planning is a formal approach that refines compound tasks through domain methods until executable primitive tasks remain.

- A compound task requires decomposition.
- A method defines an allowed domain-specific decomposition and its conditions.
- A primitive task can be executed directly by the runtime.

HTN is useful where reusable procedures, consistency, auditability, and allowed methods matter more than open-ended creativity. Its strengths depend on the quality and freshness of the domain model. Building and maintaining that model is expensive, unmodelled tasks remain difficult, and stale methods reproduce stale behaviour.

LLMs and HTN can be combined. An LLM can interpret natural-language intent and extract parameters, an HTN planner can select governed methods, the execution system can run permitted primitive tasks, and an LLM can handle language-heavy steps or explain results. The model handles ambiguity while the HTN layer constrains procedure.

## Goals and policies

Goals and policies affect every decision strategy but are not peer planning algorithms.

A goal defines the desired state or measurable acceptance condition. Weak goals such as "improve the system" invite drift. Strong goals specify observable completion, including tests, evidence, output fields, or terminal status.

A policy determines whether a proposed action may proceed, requires approval, or must be denied. Policies may cover tools, permissions, data access, cost, risk, privacy, network access, reversibility, and human approval.

Important policy enforcement should live in application or infrastructure controls such as scoped credentials, network restrictions, sandboxes, tool allowlists, spending limits, and approval gates. The agent should not be the sole authority deciding whether its own restriction applies.

## Production hybrid

A robust production architecture commonly combines the strategies:

1. a Planner creates a versioned plan with dependencies, budgets, outputs, and approval boundaries;
2. a State Machine persists progress and selects a ready step;
3. a bounded Executor uses fixed logic or ReAct within the step contract;
4. a Verifier checks evidence, schema, requirements, and completion;
5. a Replanner performs local repair or revises remaining work only after a valid trigger;
6. a policy layer authorises tools, data, cost, risk, and high-impact actions.

Responsibilities should remain explicit. The Planner must not perform the Executor's research, the Executor must not silently redefine the goal, the Verifier must distinguish local repair from global replan, and the Replanner must preserve valid work and respect a replan limit.

## Selection sequence

Use the least flexible mechanism that can reliably complete the task:

1. keep deterministic work in fixed logic;
2. add bounded ReAct when the next useful action depends on an observation;
3. add Plan-and-Execute when global coverage, ordering, dependencies, or visible progress matter;
4. add adaptive replanning only when material premises can change and valid triggers can be detected;
5. add hierarchy when a flat plan is too large or subgoals need distinct ownership and context;
6. use HTN when governed domain procedures can be modelled;
7. use an external planner or solver when formal feasibility or optimisation is required.

The production objective is deliberate placement of flexibility, not maximum planning freedom. Fixed outer control, explicit plans where global coverage matters, bounded local adaptation where observations matter, verification before acceptance, and versioned replanning after real invalidation form a more reliable system than any one pattern used everywhere.
