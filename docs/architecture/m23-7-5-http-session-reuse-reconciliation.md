# M23.7.5 HTTP Session Reuse Repair Reconciliation

Issue: #441. Parent: #430.

## Measured trigger

The first valid redacted live latency receipt completed all eight bounded internal
synthetic probes with zero errors and zero output influence, but was rejected on the
unchanged canonical shadow p95 budget.

Measured evidence:

- receipt SHA-256: `cb3bfc59dcc471ac924c8a3bc73d6307d99cffa6d26a0a6e6fbdd64fbde8076f`;
- sample count: 8;
- success count: 8;
- error rate: 0.0;
- provider p95: 2242 ms;
- Qdrant p95: 2226 ms;
- total shadow p95: 3381 ms;
- primary dispatch overhead p95: 1 ms;
- overlap@5 mean: 0.25;
- budget violation: `shadow-latency` only.

The canonical 1200 ms shadow and 25 ms dispatch budgets were not changed.

## Root cause addressed

The live transport created a new `httpx.Client` for each Cloudflare embedding, each
Qdrant query and each collection operation. Eight probes therefore repeated TLS and
proxy connection setup many times. A budget decision before removing this avoidable
transport overhead would not have been evidence-based.

## Accepted repair

Implementation PR #442:

- creates one bounded Cloudflare HTTP client per observation;
- creates one bounded Qdrant HTTP client per observation;
- reuses those sessions across collection snapshots, sampling, eight embeddings and
  eight read-only queries;
- explicitly closes both sessions through context managers in the live and diagnostic
  CLIs;
- preserves strict-mode-safe read-only Qdrant request bodies and complete client-side
  point identity and ACL validation;
- adds tests proving exactly two clients are created, reused, contain no write/delete
  surface and are closed;
- changes no provider/model, collection, probe count, ranking, payload, privacy,
  authority, production, R2, Source, pointer or answer-serving state.

## Accepted implementation evidence

- implementation issue: #441;
- implementation PR: #442;
- accepted implementation head: `6094885473a585d5434fc23a5cffd70e1d7ff189`;
- implementation merge: `37460a71ea56b989d16e44570f27fa002ff7b5db`.

Accepted exact-head runs:

- M23.7.5 Bounded Live Shadow `29404782917` (run 14), success;
- M23.7.5 Latency Diagnostic Evidence `29404782839` (run 4), success;
- CI `29404782906` (run 900), success;
- R2 Release Integration `29404782782` (run 605), success;
- M18 Graph v2 acceptance `29404782843` (run 336), success.

## Remaining parent gate

The transport repair does not claim the 1200 ms budget now passes. The operator must
pull main and rerun the same redacted latency diagnostic. That second receipt will show
whether connection reuse removes the measured overhead.

The observed overlap@5 mean of 0.25 remains a separate retrieval-drift signal. It is not
changed or hidden by this repair and must be included in final M23.7.5 review.

Issue #430 remains open and M23.7.6 remains blocked until a real post-repair receipt is
reviewed and final M23.7.5 reconciliation merges.

Production mutation dispatched: false.
