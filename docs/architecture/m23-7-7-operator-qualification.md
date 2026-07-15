# M23.7.7 Cold-Start Operator Qualification

Issue: #449. Parent: #408.

## Purpose

M23.7.7 proves that an operator with only a clean repository checkout can reconstruct the
M23.7 operating state, run all required deterministic checks, diagnose a bounded failure,
verify lexical rollback and produce a closeout package for M23.7.8.

Prior chat history is explicitly outside the evidence boundary. The qualification uses no
secrets, network, provider, Qdrant operation or production mutation.

## Entry baseline

- Engine: `a71d3e0e6f42b8de4f6c370bd988c7505161567f`;
- M23.7.1 contract:
  `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 evaluation:
  `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- M23.7.3 replay:
  `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`;
- M23.7.4 composition:
  `6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7`;
- M23.7.5 final evidence:
  `c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71`;
- M23.7.6 receipt:
  `a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1`;
- M23.7.6 rebuild descriptor:
  `53e048805c60e9c08d23c67cc96e0b84ae75c0ee9fe121c1776cd28c5053e8e7`.

The accepted read-only production snapshot remains release
`20260708T040116Z-69a9f445699a` with pointer SHA
`38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`.
It must be refreshed before any later promotion decision.

## Challenge boundary

The machine-readable challenge is:

`pilot/m23/m23-7-7-operator-challenge.json`

It contains only:

- task identifiers;
- procedures;
- repository evidence paths;
- required output field names;
- cold-start and no-mutation rules.

It does not contain expected values, a correct-answer map or a hidden answer key. The
validator independently derives the canonical submission from repository evidence and
existing executable builders.

## Qualification tasks

A cold-start operator must complete ten tasks:

1. verify the M23.7.1 through M23.7.6 identity chain and Source PR #19 state;
2. verify the accepted read-only production snapshot and refresh requirement;
3. inspect the 107-point ingestion identity and false authority flags;
4. execute the deterministic held-out negative gate;
5. execute frozen lexical-authoritative shadow replay;
6. execute candidate-only grounded answer composition;
7. diagnose the frozen `qdrant-unavailable` failure scenario;
8. verify immediate candidate-independent lexical rollback;
9. inspect internal Graph Explorer deployment and exposure boundaries;
10. preserve blockers and produce the deterministic closeout package.

## Runbook

From a clean checkout:

```bash
python -m pip install -e '.[dev]'
python scripts/m23_7_7_operator_qualification.py \
  --output /tmp/m23-7-7-closeout.json \
  --report-output /tmp/m23-7-7-report.json
```

Run it a second time to different output paths and compare the bytes. No environment
variables, credentials or external services are required.

## Passing qualification

Operator qualification passes when all ten tasks are reconstructed correctly and the
closeout bytes are deterministic. Passing qualification is separate from candidate
promotion eligibility.

The expected operator status is:

```text
qualified_with_blockers
```

The following blockers must remain present:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

The operator score may be 100 while promotion eligibility remains false.

## Explorer boundary

Qualification must preserve:

- internal Cloudflare Access authentication;
- internal preview deployment posture;
- `GRAPH_EXPLORER_ENABLED=false` by default;
- read-only operation;
- no browser persistence;
- no browser network client;
- no write-back;
- no public route.

## Phase gate

M23.7.8 remains blocked until:

- the M23.7.7 implementation PR merges by expected head;
- an independent reconciliation PR merges;
- issue #449 closes completed.

M23.7.8 owns the later `promote | hold | repair | reject` decision. M23.7.7 makes no
promotion decision and dispatches no production change.

## Authority boundary

Production retrieval remains lexical. Source PR #19 remains draft, open and unmerged.
No live traffic, provider call, Qdrant operation, deployment, pointer mutation, R2
mutation, Source mutation, Worker/Queue mutation, public Explorer, permanent ledger,
credential rotation, promotion or Graph Neural Retrieval is dispatched.

Production mutation dispatched: false.
