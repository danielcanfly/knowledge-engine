# ACL and Audience Invariants

## Audience order

From least to most restrictive:

```text
public < internal < confidential < restricted
```

The effective audience of a derivative is the most restrictive audience among all inputs and applicable policies.

## Required fields

Every snapshot records:

```text
audience
access_policy
acl_status
acl_observation_source
owner
license
```

`access_policy` is structured and may include principals, groups, domain restrictions, link-sharing state, and connector-native evidence references.

## Non-broadening rule

For every derivation:

```text
rank(output.audience) >= max(rank(input_i.audience))
```

and output principals must be a subset/intersection allowed by all inputs.

## Unknown metadata

- unknown audience defaults to `restricted`;
- unresolved ACL sets `acl_status=unresolved`;
- unresolved ownership or license blocks `accepted_for_compilation` unless a documented operator policy resolves it;
- absence of metadata is not evidence of public access.

## Multi-source synthesis

A concept or claim derived from multiple snapshots inherits:

- the most restrictive audience;
- the intersection of allowed principals;
- all source-level legal/license constraints;
- claim-level provenance for each supporting source.

A later public source does not declassify a restricted claim automatically.

## Permission changes

A connector-observed permission change creates a new snapshot/evidence event even when bytes are unchanged. It may trigger:

- source-head update;
- derived-knowledge impact analysis;
- cache invalidation;
- release withdrawal or rebuild.

This propagation is implemented in later milestones, but M10 snapshot identity must preserve the facts needed to perform it.

## Query boundary

Raw snapshots are never query-time fallback merely because canonical retrieval returns no result. Query access must be explicitly governed and audience-filtered.

## Validation failures

Reject or quarantine when:

- output audience is less restrictive;
- access policy is missing or malformed;
- connector claims public but permission evidence is unresolved;
- a source contains principals not representable by current policy;
- a derivative omits source ACL lineage;
- a normalized artifact is placed in a public bucket/key namespace without approved public status.
