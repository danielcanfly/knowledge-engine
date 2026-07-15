# M23.7.8 Final Reconciliation

Parent issue: #408. Implementation issue: #455.

## Outcome

M23.7.8 completed the final M23.7 decision gate with:

```text
repair
```

M23.7 closes as:

```text
complete_with_repair_decision
```

This is an evidence-backed no-promotion closure. It does not enable candidate mode,
semantic response authority or production semantic retrieval.

## Decision rationale

The final decision is not `promote` because the accepted live evidence still carries:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

The final decision is not `reject` because deterministic offline retrieval, security,
candidate-answer grounding, failure isolation, deterministic rebuild, lexical rollback
and cold-start operator qualification passed. `hold` would preserve safety but would not
convert the already-localised evidence gaps into bounded work. `repair` is therefore the
only selected option.

## Accepted implementation

- implementation issue: #455;
- implementation PR: #458;
- accepted implementation head:
  `9949225070c75cc89f67bfed3966819f2998f958`;
- expected-head squash merge:
  `f815e2a8b7ee15da87a1c58d0ff032c6e9b355c3`;
- final decision report:
  `pilot/m23/m23-7-8-final-decision-report.json`;
- repair handoff:
  `pilot/m23/m23-7-8-repair-handoff.json`;
- decision packet SHA-256:
  `89e5f6c8e748e089d0360ffc6a440b91bbb85a157397c1e6a9aa706f26a10f18`;
- report SHA-256:
  `b8d4278dec2c777a2ed3c888ff20f8e5d4e5a80315dc8b15179f4e63045fe92f`;
- repair handoff SHA-256:
  `7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9`.

The initial implementation head was rejected only for source line-length formatting.
The accepted head changed formatting without changing packet, report, handoff or digest
identities.

## Exact-head workflow evidence

All required workflows passed at the accepted implementation head:

- M23.7.8 Final Decision, run `29411979225`, run number 2;
- CI, run `29411979155`, run number 928;
- R2 Release Integration, run `29411979100`, run number 623;
- M17 Architecture Canon Acceptance, run `29411979138`, run number 219;
- M18 Graph v2 acceptance, run `29411979107`, run number 364.

The dedicated workflow executed 14 fail-closed tests, regenerated the final decision
report and repair handoff, compared both artifacts byte-for-byte with their committed
versions, scanned decision and authority fields, and compiled the accepted scope.

## Live blocker evidence

Latency remains unresolved:

- canonical shadow p95 budget: 1200 ms;
- accepted post-session-reuse shadow p95: 1731 ms;
- over budget: 531 ms;
- budget changed: false.

Retrieval quality remains unresolved:

- accepted live overlap@5 mean: 0.25;
- accepted live overlap drift: -0.70;
- retrieval blocker cleared: false.

No offline pass, reliability proof or operator score was allowed to overwrite these live
acceptance facts.

## Repair handoff

Three separately governed workstreams are required:

1. `R1 live_probe_semantic_alignment`
   - versioned synthetic probes;
   - offline-to-live query identity mapping;
   - deterministic relevance set;
   - independent reconciliation.
2. `R2 latency_path`
   - component latency receipts;
   - connection reuse preserved;
   - regional or binding path comparison;
   - locked 1200 ms budget with no inflation.
3. `R3 bounded_live_reobservation`
   - at most eight synthetic probes;
   - zero error, ACL and output-influence rates;
   - shadow p95 at or below 1200 ms;
   - retrieval-quality blocker cleared;
   - independent acceptance reconciliation.

Each workstream requires its own issue, branch, exact-head CI, expected-head merge and
independent reconciliation. Completion of all workstreams still requires a new explicit
promotion decision.

## M23.7 closure

After this reconciliation merges:

- issue #455 may close completed;
- parent issue #408 may close completed;
- M23.7 is complete as an evaluation and decision phase;
- semantic retrieval remains unpromoted;
- the next legal action is to open separately governed repair workstreams.

## Authority boundary

Production retrieval remains lexical. Candidate mode remains disabled. Promotion
eligibility remains false.

Source PR #19 remains open, draft and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

No live traffic, user sampling, production query mirroring, answer serving, deployment,
production pointer, R2 mutation, Source mutation, Source PR merge, Qdrant write/delete,
Worker/Queue mutation, public Graph Explorer, permanent ledger mutation, credential
rotation, promotion or Graph Neural Retrieval was dispatched.

Production mutation dispatched: false.
