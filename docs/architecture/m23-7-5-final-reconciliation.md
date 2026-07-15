# M23.7.5 Final Reconciliation

Parent issue: #430. Reconciliation issue: #444.

## Outcome

M23.7.5 is complete as a bounded, privacy-safe, fail-closed observation.

The observation did not pass the locked acceptance thresholds. This reconciliation does
not alter the latency budget, retrieval contract, production authority or candidate
eligibility. It records the observed no-go faithfully and carries the blockers forward
to the final M23.7 decision package.

Outcome:

```text
completed_fail_closed
```

Carry-forward blockers:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

This is not a promotion decision. It grants no production or candidate-mode eligibility.

## Exact identities

- Engine base before this reconciliation: `c9c7f0f84596afc4be0046bd074d16ff31ab107b`;
- candidate release: `m23cand-c7fbec7e945e79d05d3263b0`;
- candidate manifest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`;
- Qdrant release: `m23pilot-a07eb79e381ca7e635cc9139`;
- Qdrant manifest: `a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`;
- collection: `llm_wiki_m23_pilot_bge_m3_1024`;
- expected points: 107;
- vector: named `default`, 1024 dimensions, Cosine;
- Source PR #19: open, draft, unmerged at
  `deb3ad1e631c2149183d10561fbceb0a1848a989`.

## Locked budgets

The canonical budgets were not changed:

- shadow p95: at most 1200 ms;
- primary dispatch overhead p95: at most 25 ms;
- error rate: 0.0;
- ACL violation rate: 0.0;
- output influence rate: 0.0.

## Observation evidence

### Before bounded HTTP session reuse

Receipt SHA-256:
`cb3bfc59dcc471ac924c8a3bc73d6307d99cffa6d26a0a6e6fbdd64fbde8076f`

- samples: 8;
- successes: 8;
- error rate: 0.0;
- provider p95: 2242 ms;
- Qdrant p95: 2226 ms;
- total shadow p95: 3381 ms;
- primary dispatch overhead p95: 1 ms;
- overlap@5 mean: 0.25;
- outcome: rejected on `shadow-latency`.

### After bounded HTTP session reuse

Receipt SHA-256:
`493515fce1bdeb1c7155ea69c198f658c0cf05f83314a905bf2d945152dc4b3e`

- samples: 8;
- successes: 8;
- error rate: 0.0;
- provider p95: 1328 ms;
- Qdrant p95: 576 ms;
- total shadow p95: 1731 ms;
- primary dispatch overhead p95: 1 ms;
- overlap@5 mean: 0.25;
- overlap drift versus frozen replay: -0.70;
- outcome: rejected on `shadow-latency`.

## Interpretation

Session reuse removed substantial avoidable transport cost:

- provider p95 decreased by 914 ms, approximately 40.8%;
- Qdrant p95 decreased by 1650 ms, approximately 74.1%;
- total shadow p95 decreased by 1650 ms, approximately 48.8%.

The post-repair 1731 ms total still exceeds the locked 1200 ms budget by 531 ms.
The provider p95 alone is 1328 ms, so the remaining latency breach is not explained by
primary dispatch overhead or repeated Qdrant connection setup.

Retrieval overlap remained exactly 0.25 before and after the transport repair. The
transport change therefore did not alter ranking semantics and did not repair the
separate retrieval-quality drift.

## Passed invariants

- the bounded observation executed against the isolated non-production collection;
- eight of eight synthetic probes completed;
- error rate remained zero;
- primary dispatch overhead remained within budget;
- collection and release identities remained exact;
- the observation remained read-only;
- no user query was sampled;
- no raw query or answer was durably persisted;
- candidate output remained discarded;
- output influence remained zero;
- production retrieval remained lexical;
- Source PR #19 remained open, draft and unmerged;
- no production, pointer, R2, Source, Qdrant write/delete or answer-serving mutation was
  dispatched.

## Failed acceptance areas

### Latency

The canonical shadow p95 gate failed after the authorised transport repair. No further
budget adjustment or latency repair is authorised in this reconciliation.

### Retrieval quality

The exact-section overlap@5 mean remained 0.25 with drift -0.70 versus frozen replay.
This is retained as a quality blocker for M23.7.8 and must not be hidden by later
reliability testing.

## Sequence decision

M23.7.5 execution and reconciliation are complete. M23.7.6 may begin because its scope
is failure injection, rebuild and lexical rollback proof, not promotion.

M23.7.6 must preserve these M23.7.5 blockers and must not claim semantic retrieval is
eligible for production or candidate-mode exposure. The final `promote | hold | repair |
reject` decision remains owned by M23.7.8.

## Durable evidence

Machine-readable aggregate evidence:

`pilot/m23/m23-7-5-final-observation-evidence.json`

Evidence payload SHA-256:

`c8e7d3d672bc848ab22cdef8ca55b8ed444aacae294c4d662e018bedb7ed4e71`

Production mutation dispatched: false.
