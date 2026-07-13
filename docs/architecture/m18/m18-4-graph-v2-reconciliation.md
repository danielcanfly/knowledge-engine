# M18.4 Graph Schema v2 Compiler Reconciliation

Status: complete  
Issue: #255  
Production mutation dispatched: false

## Merged identity

Engine changed from `2b82fb30031a63a63aaf192019ce2d2568ed53bf` to
`b843d9e847ec0533a57960317c579c850265abf0` through PR #256.

## Delivery

- `artifacts/graph-v2.json` is emitted as an additional release artifact.
- Existing `artifacts/graph.json` v1 remains the Runtime compatibility artifact.
- Nodes include stable identity, description, audience, status, confidence,
  governed tags and aliases, path, and provenance record.
- Typed edges use deterministic IDs derived only from schema version, immutable
  endpoints, relation type, direction, and sorted qualifiers.
- Directed authoring relations produce deterministic generated inverse semantics.
- Edge audience is the more restrictive endpoint audience.
- Generic Markdown links remain separate and are not promoted to typed facts.
- Missing targets, unknown types, direction drift, alias collisions, duplicate
  edge identities, and renderer-specific fields fail closed.
- Legacy bundles without a graph profile remain buildable only when they declare
  no typed relations.

## Exact-head acceptance

Final PR head: `5f011c6a357138e96a670f3370b0c21c2f5f34c3`.

Passed on that exact head:

- CI run #567.
- M18 Graph v2 acceptance run #3.
- M17 Architecture Canon Acceptance run #7.
- R2 Canary run #227.
- R2 Release Integration run #416.

The workflows exercised validation and isolated integration paths; no production
promotion or production pointer update was dispatched.

## Compatibility and baseline

The current five Source concepts still declare zero typed relations. Graph v2
therefore compiles five nodes and zero typed edges until the separately governed
M18.5 migration. Runtime continues to load graph v1; relation-aware retrieval is
not enabled.

## Mutation reconciliation

No candidate release, production release, production pointer, permanent R2
release object, credential, permanent ledger, lifecycle state, rollback state,
Graph Explorer, embedding index, extraction job, multi-hop planner, or Graph
Neural Retrieval was created or changed.

M18.4 is complete when this reconciliation change passes exact-head Engine CI
and merges.
