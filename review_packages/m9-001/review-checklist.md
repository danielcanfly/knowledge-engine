# M9-001 Human Source Review Checklist

Status: `pending_human_review`

Parent: `#99`

Tracker: `#102`

Batch: `m9-001-agent-planning-strategies`

Target: `bundle/concepts/agent-planning-strategies.md`

## Reviewer decision

Allowed decisions:

- `approve`
- `request_changes`
- `reject`

Approval must be explicit. Silence, PR merge, CI success, or package validation does not authorise canonical Source writes.

## Scope

- [ ] The concept is universal engineering knowledge rather than article navigation or project-specific code.
- [ ] Fixed Logic, bounded ReAct, Plan-and-Execute, adaptive planning, hierarchical planning, and HTN are represented accurately.
- [ ] The concept does not present the strategies as a maturity ladder.
- [ ] Local repair and global replanning remain distinct.
- [ ] Plan generation is not treated as proof of feasibility.
- [ ] Goals and policies are cross-cutting controls rather than peer planning algorithms.

## Boundary with existing concepts

- [ ] M6 remains the higher-level six-dimensional architecture map.
- [ ] M8 remains the definition of Direct, Pipeline, Router, State Machine, and DAG execution structures.
- [ ] M9 focuses on node-level decision, planning, verification, and replanning.
- [ ] Composability is explicit: a State Machine may contain bounded ReAct, and a plan may execute through a DAG.
- [ ] No canonical claim duplicates or contradicts M6 or M8.

## Provenance and citation

- [ ] Origin repository, commit, path, and blob SHA match the reviewed Part 3 article.
- [ ] All 11 material claims have meaningful section locators.
- [ ] No claim depends on an uncited external vendor statement.
- [ ] The public citation URL points to Part 3 English.
- [ ] The proposed concept contains no copied image paths, figure captions, or article navigation.

## Audience and ACL

- [ ] The concept is suitable for the `public` audience.
- [ ] The proposed confidence of `0.9` is acceptable.
- [ ] The public concept does not contain the internal ACL negative fixture phrase.
- [ ] The proposed `cobalt heron checkpoint` fixture will be introduced only through an approved internal-only boundary record, not in the public concept.
- [ ] Raw fallback must remain disabled.

## Production engineering quality

- [ ] Bounded ReAct includes step contracts, budgets, progress, duplicate detection, completion, and escalation.
- [ ] Plan steps include inputs, dependencies, outputs, completion criteria, failure policy, budget, and provenance.
- [ ] Replanning includes explicit triggers, plan versions, diffs, preserved work, and limits.
- [ ] Hierarchical planning includes integration ownership and parent/child completion.
- [ ] HTN is described through compound tasks, methods, and primitive tasks.
- [ ] The production hybrid keeps Planner, Executor, Verifier, Replanner, State Machine, and policy responsibilities separate.

## Mutation boundary

- [ ] Review status remains `pending_human_review` until Daniel decides.
- [ ] `canonical_write_authorized` remains `false` before approval.
- [ ] No Knowledge Source commit exists for this package yet.
- [ ] No candidate has been built or published.
- [ ] No R2 object, production request, ledger entry, or production pointer has been changed.

## Decision record requirements

For `approve`, record:

- reviewer identity;
- reviewed timestamp;
- approved audience;
- approval of content scope and provenance;
- approval of M6/M8 boundary;
- approval of ACL fixture strategy;
- explicit authorisation to create the canonical Source PR.

For `request_changes`, list exact required edits and keep canonical writes disabled.

For `reject`, record the reason and keep the batch at `planned` or close it through a separately reviewed lifecycle decision.
