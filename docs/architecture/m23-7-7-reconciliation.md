# M23.7.7 Reconciliation

Parent issue: #408. Implementation issue: #449.

## Outcome

M23.7.7 completed the cold-start operator qualification and deterministic closeout
package without granting semantic production authority or promotion eligibility.

Accepted outcome:

```text
qualified_with_blockers
```

Qualification score:

```text
10 / 10 tasks
100 percent
```

The two M23.7.5 blockers remain unchanged:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

## Accepted implementation

- implementation PR: #450;
- accepted implementation head:
  `84275ee03723d0f18267789b6e4efc672eb02082`;
- expected-head squash merge:
  `64ee780f85051c52eb84d83bceb60dd0d3ba3682`;
- challenge:
  `pilot/m23/m23-7-7-operator-challenge.json`;
- challenge SHA-256:
  `ebaef60f3274e4321967e175e2e90e3498a558a7a1a0704d8706b9920769417a`;
- deterministic closeout:
  `pilot/m23/m23-7-7-operator-closeout.json`;
- operator qualification SHA-256:
  `e60e6825d72f8848b90cf55f2c14e8bb70c6cf0dda5990feadb28b013bbedce8`.

## Exact-head workflow evidence

Core required workflows passed at the accepted implementation head:

- M23.7.7 Operator Qualification, run `29407848102`, run number 7;
- CI, run `29407848116`, run number 917;
- R2 Release Integration, run `29407848484`, run number 616;
- M17 Architecture Canon Acceptance, run `29407848025`, run number 212;
- M18 Graph v2 acceptance, run `29407848029`, run number 353.

The narrow Ruff policy update caused the complete matching acceptance matrix to run at
the same exact head. Every triggered workflow completed successfully, including R2
Canary, M16 security/recovery/containment checks, M17 operator and GA checks, M23.2
through M23.6 compatibility checks, and the M23.4 human-review boundary check.

Earlier heads were rejected before acceptance because of formatting-only Ruff failures.
No rejected head passed the operator gate, produced accepted evidence or merged. The
accepted head changed no runtime authority or evidence identity in response to those
formatting failures.

## Cold-start qualification proof

The operator challenge disclosed only task identifiers, procedures, repository evidence
paths and required output field names. It contained no expected values or hidden answer
key.

The exact-head workflow executed from a clean Ubuntu checkout with:

- no prior chat context;
- no secrets;
- no external network dependency in the qualification runner;
- no provider call;
- no Qdrant read, write or delete;
- no production mutation.

The workflow generated the closeout twice and compared the bytes. It then compared the
newly generated closeout with the committed immutable closeout. All byte comparisons
passed.

## Qualified tasks

The cold-start operator independently completed ten tasks:

1. verified the M23.7.1 through M23.7.6 evidence identities and Source PR #19 state;
2. verified the accepted read-only production snapshot and refresh requirement;
3. verified the frozen 107-point ingestion identity and false authority flags;
4. executed the 64-case held-out retrieval and security gate;
5. executed the frozen lexical-authoritative shadow replay;
6. executed candidate-only grounded answer composition;
7. diagnosed the frozen `qdrant-unavailable` failure;
8. proved immediate lexical-only rollback without candidate dependency;
9. verified the internal, read-only and disabled-by-default Graph Explorer boundary;
10. produced the deterministic closeout with both blockers preserved.

## Production pointer and ingestion state

The accepted read-only production snapshot remains:

- release: `20260708T040116Z-69a9f445699a`;
- release manifest:
  `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`;
- pointer SHA-256:
  `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`;
- refresh required before promotion: true;
- remote mutation dispatched: false.

The non-production semantic pilot remains:

- collection: `llm_wiki_m23_pilot_bge_m3_1024`;
- points: 107;
- named vector: `default`;
- dimension: 1024;
- distance: Cosine;
- membership: `evaluation-only-pending-proposal`;
- canonical knowledge: false;
- candidate release eligible: false;
- production authority: false.

## Content-quality and answer checks

The offline 64-case gate passed with Recall@5, MRR@10, nDCG@10 and citation coverage at
1.0. Error, ACL violation, stale-source acceptance, unsupported-claim and prompt-injection
success rates were zero.

Frozen shadow replay retained lexical production authority, discarded candidate output,
and recorded zero semantic output influence. Candidate-only answer composition answered
all 16 positive cases, abstained on all 48 negative cases, preserved complete citation
coverage and recorded zero unsupported claims, citation mismatches, prompt-injection
success or candidate answer influence.

These deterministic offline results do not clear the separate M23.7.5 live latency and
retrieval-quality blockers.

## Failure and rollback proof

The operator diagnosed the frozen `qdrant-unavailable` candidate-query failure using the
bounded failure class. Lexical IDs before and after were byte-identical, candidate results
were empty, raw exception text was not persisted and output influence remained false.

Rollback remains immediate `lexical-only` operation. It requires no semantic provider,
Qdrant, Worker, Queue, candidate Runtime or Graph Explorer dependency. Production
retrieval never changed from lexical.

## Graph Explorer boundary

The accepted Explorer posture remains:

- Cloudflare Access fixed-audience authentication;
- internal preview deployment posture only;
- `GRAPH_EXPLORER_ENABLED=false` by default;
- internal-only and read-only;
- editing and write-back disabled;
- browser network client disabled;
- browser persistence disabled;
- public route disabled;
- renderer `sigma@3.0.3`.

## Phase decision

M23.7.7 implementation and reconciliation are complete after this reconciliation PR
merges and issue #449 closes completed. M23.7.8 may then begin and owns the final
`promote | hold | repair | reject` decision.

Operator qualification does not imply candidate qualification. M23.7.8 must consume both
carry-forward blockers and must not grant promotion while required evidence remains
unsatisfied.

## Authority boundary

Source PR #19 remains open, draft and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

No live traffic, user sampling, provider call, Qdrant operation, deployment, production
pointer mutation, R2 mutation, Source mutation, Source PR merge, Worker/Queue mutation,
public Graph Explorer, permanent ledger mutation, credential rotation, promotion decision
or Graph Neural Retrieval was dispatched.

Production mutation dispatched: false.
