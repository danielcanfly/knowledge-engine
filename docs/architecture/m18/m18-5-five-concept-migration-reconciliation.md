# M18.5 Five-Concept Migration Reconciliation

Status: complete  
Issue: #258  
Production mutation dispatched: false

## Merged identities

| Boundary | Before | M18.5 merged identity |
|---|---|---|
| Source content migration | `0c620bb5f1d8e3214cc5c96a0d93900d4737db93` | `1a4b4030b6b25a58ff3edba204e303ae1f95b931` |
| Source exact-Engine gate | `1a4b4030b6b25a58ff3edba204e303ae1f95b931` | `087f96b94d045f1f096ad7a3cab0c9ac2f3c5d04` |
| Engine compiler | `b843d9e847ec0533a57960317c579c850265abf0` | unchanged |
| Engine main before reconciliation | `5689a1d4b7dee59107dec6195627c986da2313c5` | unchanged |

## Governed migration

All five concepts now carry controlled tags and non-colliding aliases:

- five concepts;
- nineteen tag assignments;
- ten normalized aliases;
- three authored canonical relations;
- five compiled typed edges after two directed inverse edges are generated.

The reviewed authored relation set is exactly:

1. `agent-execution-paths part_of six-dimensional-map-of-llm-agent-architectures`;
2. `agent-planning-strategies part_of six-dimensional-map-of-llm-agent-architectures`;
3. `agent-planning-strategies complements agent-execution-paths`.

The first two use reviewed structural basis tied to the two lenses explicitly
enumerated by the six-dimensional map. The third uses approved claim
`claim_execution_structure_separate_from_decision_strategy`.

Source governance and candidate delivery controls remain unconnected. Their
reviewed evidence does not support canonical relations to the agent concepts,
and the internal audience of candidate controls was not broadened.

## Source exact-head evidence

Source migration PR #16 final head:
`ee0cd18addebf0e4a0d1f8d6a9344bae09603f45`.

Passed:

- Validate Knowledge Source run #52;
- Relation validation run #18;
- Tag and alias validation run #13;
- M18.5 migration acceptance run #6.

Source exact-Engine PR #17 final head:
`5d41c8f1fb98a0f73500c5f2f7db00b14ec6ff79`.

Passed:

- Validate Knowledge Source run #54;
- Relation validation run #20;
- Tag and alias validation run #15;
- M18.5 migration acceptance run #8;
- M18.5 exact Engine build acceptance run #1.

The exact-Engine gate installed merged Engine
`b843d9e847ec0533a57960317c579c850265abf0`, built the exact Source head
twice through isolated filesystem stores, compared the full releases, and
validated graph v2 counts, inverse generation, public edge ACL, governed
metadata, and renderer neutrality.

## Permission-boundary correction

Engine PR #259 was closed without merge after its Engine-scoped token correctly
could not read the private Source repository. No token or repository permission
was broadened. Source-owned PR #17 replaced it and proved the same acceptance
contract from inside the authorized repository boundary.

## Mutation reconciliation

No candidate publication, production promotion, production pointer change,
R2 access, credential change, permanent-ledger entry, lifecycle change, rollback
change, Runtime behavior change, Graph Explorer, embedding index, extraction
job, multi-hop planner, or Graph Neural Retrieval was created or changed.

M18.5 is complete when this reconciliation change passes exact-head Engine CI
and merges.
