# M16.3 Bad Candidate and Failed Promotion Containment

M16.3 proves two different safety properties without adding a new production executor:

1. an invalid candidate is rejected before production mutation;
2. a governed promotion that fails runtime acceptance is not considered contained until the exact previous pointer and runtime behavior are restored and verified.

## Exact baseline

- Engine: `da14e96a29069e89e466762abe2ae82e6159eb9a`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Every candidate and promotion artifact binds the exact Engine, Source, candidate release and manifest, previous production release and manifest, and previous pointer SHA-256.

## Candidate containment

Candidate validation checks:

- Engine identity;
- Source identity;
- release identity;
- manifest identity;
- expected previous pointer;
- approval evidence;
- replay or duplicate operation evidence;
- production-scope leakage;
- required artifact presence;
- artifact checksum validity.

An invalid candidate is `contained` only when `production_mutated=false`. If an invalid candidate is observed after a production mutation, the decision is `uncompensated` and the report blocks the no-unauthorized-mutation gate.

A valid candidate is `not_applicable` to bad-candidate containment. This contract does not authorize its promotion.

## Failed promotion containment

The promotion observation model records evidence from an isolated drill or the existing governed lifecycle. It does not execute activation or compensation itself.

When activation occurred and runtime acceptance failed, containment requires all of the following:

- compensation state is `completed`;
- the observed pointer equals the exact previous pointer SHA-256;
- runtime is bound to the exact previous release;
- cache is bound to the exact previous release;
- a post-compensation query succeeds;
- citations are verified;
- an ACL-negative query remains denied;
- exact identity, approval, and operation evidence remain valid.

A compensation that has not begun is `compensation_required`. A completed compensation with any failed restoration or verification check is `uncompensated`. Missing or drifted evidence can never produce a contained decision.

## Closed states

Candidate validation states:

- `valid`
- `invalid`
- `unknown`

Compensation states:

- `not_required`
- `required`
- `completed`
- `failed`
- `unknown`

Containment decisions:

- `contained`
- `compensation_required`
- `uncompensated`
- `unknown`
- `not_applicable`

## Deterministic evidence

All timestamps are timezone-aware UTC. IDs and evidence codes are bounded. Duplicate candidate, attempt, artifact, and unsafe evidence identifiers are rejected. Candidate reasons, failed checks, report items, and gates are stably ordered.

The final report uses canonical JSON and SHA-256 artifact identity. Reordering equivalent input produces the same digest, while changing a finalized decision causes digest verification to fail.

## Privacy boundary

The contract has no fields for raw queries, raw answers, private excerpts, credentials, IPs, hostnames, stack traces, object URIs, or arbitrary exception text. Evidence is represented by bounded codes.

## Authority boundary

M16.3 has no authority to:

- write or repair Source;
- create or dispatch a Source PR;
- promote a candidate;
- execute rollback;
- repair a production pointer;
- purge a runtime cache;
- write, copy, or delete R2 objects;
- rotate credentials;
- perform physical deletion;
- append to permanent ledger #30.

The contract is a containment judge, not a production switchboard. Compensation evidence may describe an existing governed lifecycle action, but the evaluator cannot perform that action.
