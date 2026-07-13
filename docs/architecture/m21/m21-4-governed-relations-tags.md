# M21.4 governed typed relation and controlled tag candidates

## Status

Implementation contract for issue #322. M21.4 maps M21.3 review-only evidence into typed relation candidates and governed tag candidates. It does not approve review, mutate Source, materialize inverse graph edges, or publish candidate or production state.

## Authoritative contracts

M21.4 pins Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832` and validates two complete machine contracts:

- `knowledge-os-relation-ontology/v0.1`, ontology `daniel-knowledge-os/relation-ontology`, version `0.1.0`;
- `knowledge-os-tag-taxonomy/v0.1`, taxonomy `daniel-knowledge-os/tag-taxonomy`, version `0.1.0`.

The relation registry contains 20 governed types. Only the 12 primary authoring types may be proposed in M21.4. Eight reciprocal inverse declarations remain generated semantics and cannot be independently authored as candidate truth.

The tag registry contains four dimensions, 16 canonical tags, and three governed aliases. Alias resolution is one step only and always lands on a canonical tag.

## Input authority

The only knowledge input is a valid `knowledge-engine-extraction-candidates/v1` packet with:

- valid packet digest;
- candidate-only authority;
- canonical and production authority disabled;
- review required;
- exact Engine, Source, and pinned Foundation identity;
- unique pending-review candidates with evidence spans.

Relation mappings may reference only M21.3 `relation_hint` candidates and existing concept or entity endpoint candidates. Tag mappings may reference only a concept or entity candidate and one of that candidate's existing M21.3 controlled tags.

## Typed relation candidate

Every typed relation candidate records:

- relation hint candidate ID;
- source and target candidate IDs;
- approved primary relation type;
- explicit directed or undirected direction;
- reciprocal inverse type;
- provenance expectation;
- retrieval semantics;
- bounded approved qualifiers;
- confidence no greater than the M21.3 hint confidence;
- exact copied M21.3 evidence spans;
- pending-review and candidate-only authority.

All self-loops are forbidden by ontology v0.1. Endpoint labels must resolve through the endpoint candidate label, normalized label, or aliases. Symmetric relation duplicates normalize endpoint order and fail closed.

## Governed tag candidate

Every governed tag candidate records:

- source candidate ID;
- exact M21.3 source tag;
- canonical governed tag;
- governed dimension;
- confidence no greater than the source candidate confidence;
- exact copied source evidence spans;
- pending-review and candidate-only authority.

Unknown tags, category mismatch, absent M21.3 tag evidence, alias drift, and duplicate candidate/tag pairs fail closed.

## Determinism and integrity

Ontology and taxonomy SHA-256 values are computed over canonical JSON and stored in the output packet. Relation and tag candidate IDs bind the exact M21.3 packet identity and normalized candidate payload. Stable sorting makes replay byte-identical.

M21.4 rejects:

- ontology or taxonomy identity, registry, inverse, direction, dimension, or alias drift;
- free-form or inverse-only relation types;
- unresolved or non-concept/entity endpoints;
- label ambiguity, self-loops, duplicate normalized relations, or invalid direction;
- unsupported or secret-like qualifiers;
- confidence escalation or evidence loss;
- unknown tags, missing source tag evidence, dimension mismatch, or duplicate tag candidates;
- M21.3 packet digest, authority, candidate coverage, or Foundation identity drift.

## Output authority

The output schema is `knowledge-engine-governed-candidates/v1`. It explicitly declares:

- `authority: candidate_only`;
- `canonical_knowledge: false`;
- `production_authority: false`;
- `review_required: true`.

No candidate is approved or adopted automatically.

## Exclusions

No model/provider/network call, live connector, scheduler, queue, worker, Source edit, canonical adoption, review approval, inverse edge materialization, entity resolution, bulk Source PR, candidate or production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.5 work, cross-release merge, or Graph Neural Retrieval is included.

## Closure reconciliation

M21.4 implementation was delivered through issue #322 and implementation PR #323.

Exact identity chain:

- M21.3 reconciliation base: `672dfdbd1371f44873d24104b5dd6dfc52d598fc`;
- invalidated implementation head: `d02aee6cefe9e4a1a302c0d4891ef739b1cc2c6c`;
- final implementation head: `14efc6b46d592e3ee6d289885ad3095be9685573`;
- implementation merge: `f5107b70d279d61ecf65595dc575925a987a5c38`.

The invalidated head passed exact checkout and dependency installation but failed one Ruff E501 in a test fixture before functional tests ran. It is not acceptance evidence.

Implementation scope was exactly four added files: the M21.4 workflow, this architecture contract, the governed relation/tag module, and its acceptance tests. The final implementation head passed M21.4 Governed Relations and Tags #2, CI #671, M17 Architecture Canon Acceptance #69, M18 Graph v2 Acceptance #107, and R2 Release Integration #463.

PR #323 had no conversation comments, submitted reviews, or unresolved review threads. The merge used the recorded expected head SHA.

One invalid PR creation request using head `none` was rejected by GitHub with HTTP 422 before the canonical issue and branch existed. It created no repository object and has no evidence role.

No model/provider/network call, live connector, scheduler, worker, Source mutation, canonical adoption, review approval, inverse edge materialization, entity resolution, bulk Source PR, candidate or production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, cross-release merge, or Graph Neural Retrieval was dispatched.
