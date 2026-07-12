# M18.2 Relation Ontology and Source Schema Reconciliation

Status: complete  
Issue: #251  
Production mutation dispatched: false

## Merged identities

| Repository | Before | M18.2 main |
|---|---|---|
| Foundation | `608963e2f15e3176e3f80851bf51449411d256da` | `e53af5833193a644a4d7397b7d466ababb5e1373` |
| Source | `2126db2ed4d372d3d61464fe31a86fc0243a1f24` | `377fb5e7bc69e034e836e535294f86c296b03908` |
| Engine | `442ed223295c93592ea32d60f055b80c2fe42810` | unchanged before reconciliation |

## Foundation delivery

Foundation PR #7 established:

- renderer-neutral relation ontology schema `knowledge-os-relation-ontology/v0.1`;
- ontology `daniel-knowledge-os/relation-ontology` version `0.1.0`;
- 12 primary authoring relations;
- 8 explicit inverse-only relation declarations;
- 20 total validated relation types;
- 16 directed types and 4 symmetric self-inverse types;
- provenance expectations, allowed semantic qualifiers, and retrieval semantics;
- a deterministic validator, valid/invalid fixtures, and adversarial tests.

Contract validation run #34 passed on exact PR head `5421012564cfc26223386c701de2b63d23aea62a`.

## Source delivery

Source PR #14 established:

- exact Foundation ontology pin `e53af5833193a644a4d7397b7d466ababb5e1373`;
- graph profile `daniel-knowledge-source/graph-v0.1`;
- `x-kos-relations` declaration JSON Schema;
- fail-closed relation validation for stable targets, approved authoring type, direction, confidence, qualifiers, evidence, review subject, ACL derivation, duplicate normalization, self-loops, and profile drift;
- dedicated relation validation workflow;
- adversarial tests for unknown types, missing targets, invalid directions, self-loops, duplicates, missing claims, missing reviews, ACL downgrade, profile drift, and renderer fields.

Exact-head validation:

- Validate Knowledge Source run #38: passed.
- Relation validation run #4: passed.
- Source PR head: `8251047e548f7f327b7895d50702feb45db45a72`.

## Preserved baseline

| Measure | M18.1 | After M18.2 |
|---|---:|---:|
| concepts | 5 | 5 |
| canonical typed relations | 0 | 0 |
| concept-to-concept compiled edges | 0 | 0 until M18.4 |
| Source concept-body changes | 0 | 0 |

M18.2 adds contracts and validation only. It does not invent relationships among the current concepts.

## Authority and compatibility

- Foundation owns base relation schema and semantics.
- Source pins Foundation and owns the governed authoring profile.
- Only the 12 primary relation types are editable Source declarations.
- Inverse edges are generated semantics, not duplicate editable Source facts.
- Generic Markdown `links_to` remains distinct from typed relations.
- Graph v2 compilation is deferred to M18.4.
- Existing Runtime behavior is unchanged.
- Tags and aliases remain M18.3 work.
- Graph Neural Retrieval remains out of scope.

## Mutation reconciliation

No candidate release, production release, channel pointer, R2 object, credential, permanent ledger, lifecycle, rollback, Graph Explorer, embedding index, extraction job, or multi-hop planner was created or changed.

M18.2 is complete when this reconciliation change passes exact-head Engine CI and merges.
