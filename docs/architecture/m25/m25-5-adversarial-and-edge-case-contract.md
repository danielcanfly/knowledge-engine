# M25.5 Adversarial and Edge-Case Contract

This contract lists conditions that must fail closed or remain review-only.

## Identity ambiguity

- one label owned by multiple Source titles;
- one bilingual term owned by multiple Source concepts;
- alias target resolves to zero or more than one concept;
- proposed alias collides with another title or owner;
- alias points to another alias candidate;
- candidate and Source audiences differ.

Required behaviour: `ambiguous` or `reject`, packaging blocked, no destructive action.

## Weak evidence

- shared tags without exact identity evidence;
- lexical resemblance only;
- shared domain vocabulary;
- relation similarity only;
- one common token in otherwise different concepts.

Required behaviour: rank for review, never merge automatically.

## Parent, child and adjacent concepts

- periodic or scoped variants of a broad concept;
- capabilities that are components of a broader operating system;
- maintenance, detection or analytics activities adjacent to a broad domain;
- concepts sharing a head noun but having different operating purposes.

Required behaviour: distinct identity. A `narrower_than` proposal is permitted only as a pending,
evidence-bound candidate.

## Versioning and time

- `v1` versus `v2`;
- year-labelled policies or runbooks;
- old and new taxonomies;
- temporal replacements with similar stems.

Required behaviour: distinct identities plus optional `supersedes` proposal. No identity collapse.

## Contradiction

- opposite polarity for the same predicate and scope;
- incompatible values for the same predicate and scope;
- contradictory claims with unresolved subject identity.

Required behaviour: contradiction candidate only when the subject resolves uniquely. Contradiction
never acts as evidence for identity merge or split.

## Security and authority

- secret-like text in candidate or Source fields;
- malformed or unsigned resolver packets;
- altered policy, suite or baseline digest;
- final-split leakage into calibration;
- canonical or production authority set to true;
- relation or tag candidate with missing source binding.

Required behaviour: deterministic integrity failure.

## Resource bounds

The inherited M21 population and signal limits remain authoritative. M25.5 ranking and relation
outputs are capped by the inherited resolver population, and relation candidates remain one per
detected candidate-target relationship.
