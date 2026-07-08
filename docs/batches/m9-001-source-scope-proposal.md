# M9-001 Source Scope Proposal

Status: `planned`

Parent: `#99`

Tracker: `#100`

Approved option: `A`

## Origin

- Repository: `huaihsuanbusiness/daniel-blog`
- Commit: `27e2fe996f878f2129bf510d6a326c02f7d87be5`
- English path: `src/content/blog/the-atlas-of-agent-design-patterns-part-3/en.md`
- English blob SHA: `185fa419771942e0737cdefe10c3180505bb3c23`
- Chinese path: `src/content/blog/the-atlas-of-agent-design-patterns-part-3/zh.md`
- Chinese blob SHA: `2d3d48a066203898cc7493a85bbfdc3ea3e3f754`
- Public citation: `https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-3/`

## Intended canonical Source path

`bundle/concepts/agent-planning-strategies.md`

## Included knowledge

The proposed concept should capture reusable production engineering knowledge about:

- the distinction between outer execution structure and node-level decision strategy
- fixed decision logic for deterministic work
- bounded ReAct as local closed-loop adaptation
- explicit step contracts, progress state, completion conditions, budgets, and escalation
- Plan-and-Execute as global decomposition followed by controlled execution
- plan validation through deterministic checks, review, simulation, or formal planners
- adaptive planning with explicit replan triggers, local repair, versioning, and plan diffs
- hierarchical decomposition and parent/child completion contracts
- HTN planning through compound tasks, methods, and primitive tasks
- goals and policies as cross-cutting constraints rather than peer planning algorithms
- the production hybrid of Planner, versioned plan store, State Machine, bounded Executor, Verifier, and Replanner
- strategy selection and common planning anti-patterns

## Excluded knowledge

The canonical concept should not copy:

- article navigation or series promotion
- image captions and image paths
- long examples that do not add a reusable engineering rule
- framework or vendor marketing language
- unsupported claims or claims without retained provenance
- the complete six-dimensional architecture map already governed by M6
- the Direct, Pipeline, Router, State Machine, and DAG definitions already governed by M8
- internal candidate-delivery controls or their restricted fixture phrase

## Boundary with M6 and M8

M6 provides the higher-level six-dimensional architecture map. M8 defines outer execution structures. M9-001 defines how an agent chooses, plans, validates, executes, and revises actions inside those structures.

A State Machine may remain the outer controller while a bounded ReAct executor handles one step, or a Planner may create steps that execute as a DAG. These are composable layers, not duplicate concepts.

## Proposed acceptance

Public query:

`How do bounded ReAct, Plan-and-Execute, adaptive replanning, hierarchical planning, and HTN differ, and how should they be combined in a production agent?`

Expected citation:

`https://www.danielcanfly.com/en/blog/the-atlas-of-agent-design-patterns-part-3/`

Proposed internal-only negative fixture:

`cobalt heron checkpoint`

The fixture is only a proposal at this stage. It must not be written into canonical Source until human Source review approves the review package and audience boundary.

## Review questions

1. Is the boundary between execution structure and decision strategy explicit?
2. Are Fixed Logic, ReAct, Plan-and-Execute, adaptive planning, hierarchical planning, and HTN described without treating them as one maturity ladder?
3. Are local repair and global replanning kept distinct?
4. Are plan versions, replan triggers, budgets, policies, evidence, and verifier decisions preserved?
5. Does the production hybrid retain explicit responsibilities for Planner, Executor, Verifier, Replanner, State Machine, and policy controls?
6. Can every public claim retain the Part 3 citation?
7. Does the proposed ACL fixture avoid lexical overlap with public concepts?

## Planning boundary

This proposal creates only governance metadata and review evidence.

It does not create canonical Source content, build a candidate, upload R2 objects, append the production ledger, commit a production request, or mutate the production pointer.

After registry and contract validation, the next legal lifecycle action is `open_source_review`.
