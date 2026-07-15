# M23.7.8 Final Repair Decision

Parent issue: #408. Implementation issue: #455.

## Decision

The final M23.7 decision is:

```text
repair
```

M23.7 does not promote the semantic candidate. Production retrieval remains lexical.
The phase closes with a bounded repair decision because positive offline, security,
rollback, rebuild and operator evidence coexists with two unresolved live blockers.

## Why not the other options

`promote` is unavailable because both required live blockers remain. `reject` would be
disproportionate because deterministic offline retrieval, security, candidate-answer
composition, failure isolation, rollback and cold-start operator qualification passed.
`hold` is safe but does not convert the already-localised evidence gaps into bounded
work. `repair` preserves every authority boundary while creating explicit evidence gates.

## Complete evidence chain

The decision binds:

- M23.7.1 contract SHA
  `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 evaluation SHA
  `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- M23.7.3 replay SHA
  `b4048b3ac29fcad50ba7f43bf932b6b188068efdbf58abb2ef36f76070a0eee2`;
- M23.7.4 composition SHA
  `6e50c809e777c99d351fb297bef2a672bf8a462dc4b4ebf2a9ff5b4593601ae7`;
- M23.7.5 final observation evidence SHA
  `c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71`;
- M23.7.6 reliability receipt SHA
  `a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1`;
- M23.7.7 operator closeout SHA
  `e60e6825d72f8848b90cf55f2c14e8bb70c6cf0dda5990feadb28b013bbedce8`;
- M23.7.7 supplemental readiness packet SHA
  `93234c4ce6f225c41563427ce3b2cff7e35bf6f9471f0f9ca47642e79281260a`;
- M23.7.7 supplemental readiness report SHA
  `c81800a4626ba8c96e201a0bc7a0d0a63f61c3328bde93cb124d0f18aa8aa48f`.

## Unresolved blockers

The blockers remain exactly:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

The accepted post-session-reuse latency evidence remains:

- canonical shadow p95 budget: 1200 ms;
- observed shadow p95: 1731 ms;
- over budget: 531 ms;
- budget changed: false.

The accepted live retrieval evidence remains:

- overlap@5 mean: 0.25;
- overlap drift: -0.70;
- blocker cleared: false.

M23.7.6 reliability success and M23.7.7 operator qualification do not clear these
separate live acceptance blockers.

## Repair workstreams

### R1: Live probe semantic alignment

Create a versioned synthetic probe manifest that aligns the bounded live observation
with the frozen held-out retrieval intent without using live user queries. Pin the
query-to-relevance mapping and independently reconcile it before any new live run.

### R2: Latency path

Measure provider and Qdrant components separately, preserve connection reuse, compare
regional or binding paths, and reduce shadow p95 below the locked 1200 ms budget. Budget
inflation is forbidden.

### R3: Bounded live re-observation

After R1 and R2 complete, repeat the privacy-safe read-only observation with at most eight
synthetic probes. Acceptance requires zero error, ACL and output-influence rates, shadow
p95 at or below 1200 ms, retrieval-quality clearance and independent reconciliation.

Each workstream requires a separate issue, implementation branch, exact-head CI,
expected-head merge and independent reconciliation. Completion of all three does not
automatically promote the candidate; a new explicit promotion decision is still required.

## Durable evidence

Decision report:

```text
pilot/m23/m23-7-8-final-decision-report.json
```

Repair handoff:

```text
pilot/m23/m23-7-8-repair-handoff.json
```

Decision packet SHA:

```text
89e5f6c8e748e089d0360ffc6a440b91bbb85a157397c1e6a9aa706f26a10f18
```

Decision report SHA:

```text
b8d4278dec2c777a2ed3c888ff20f8e5d4e5a80315dc8b15179f4e63045fe92f
```

Repair handoff SHA:

```text
7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9
```

## Phase closure

After implementation and independent reconciliation merge, issue #455 and parent #408
may close completed. The closure means M23.7 reached an evidence-backed decision, not
that semantic retrieval was accepted.

The next legal action is to open separately governed repair workstreams. Production
retrieval remains lexical throughout.

## Authority boundary

Source PR #19 remains open, draft and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

Candidate mode remains disabled. Promotion eligibility remains false. No live traffic,
user sampling, production query mirroring, answer serving, deployment, production pointer,
R2 mutation, Source mutation, Source PR merge, Qdrant write/delete, Worker/Queue mutation,
public Graph Explorer, permanent ledger mutation, credential rotation, promotion or Graph
Neural Retrieval is dispatched.

Production mutation dispatched: false.
