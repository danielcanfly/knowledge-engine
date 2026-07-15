# M23.7.6 Reconciliation

Parent issue: #408. Implementation issue: #446.

## Outcome

M23.7.6 completed the deterministic failure-injection, rebuild and lexical rollback
proof without granting semantic production authority.

Accepted outcome:

```text
pass
```

The M23.7.5 blockers remain unchanged:

```text
blocked_pending_latency
blocked_pending_retrieval_quality
```

No promotion eligibility is granted.

## Accepted implementation

- implementation PR: #447;
- accepted implementation head:
  `7d739d8ae95a68b949eb8cd4a5fb3c8535bfec9e`;
- expected-head squash merge:
  `f1bde1861f6b14c606948a7f2ce89c6a3dfe83f6`;
- deterministic receipt:
  `pilot/m23/m23-7-6-failure-rebuild-rollback-evidence.json`;
- receipt SHA-256:
  `a394195ffd207028f9f9606b4c8cfc745687edb593185efbda5cf25dafe452e1`;
- rebuild descriptor SHA-256:
  `53e048805c60e9c08d23c67cc96e0b84ae75c0ee9fe121c1776cd28c5053e8e7`.

## Exact-head workflow evidence

All required workflows passed at the accepted implementation head:

- M23.7.6 Failure Rebuild Rollback, run `29406645930`, run number 2;
- CI, run `29406645865`, run number 907;
- R2 Release Integration, run `29406645979`, run number 608;
- M17 Architecture Canon Acceptance, run `29406645899`, run number 204;
- M18 Graph v2 acceptance, run `29406645896`, run number 343.

The first implementation head was rejected only because the committed receipt used
pretty JSON while the CLI emitted canonical single-line JSON. Its quality tests passed.
The accepted head canonicalised only the receipt bytes; contract logic and evidence
identities did not change.

## Accepted proofs

### Failure isolation

Ten deterministic failure classes were exercised:

- Cloudflare timeout and unavailable;
- Qdrant timeout and unavailable;
- collection identity drift;
- point or release identity drift;
- vector contract drift;
- ACL rejection;
- response shape drift;
- circuit breaker open after three failures.

For every injected fault:

- failure classification was exact and bounded;
- raw exception text was not persisted;
- candidate result IDs were empty;
- candidate output was discarded;
- lexical result IDs before and after were byte-identical;
- lexical primary continued;
- rollback was immediate and candidate-independent;
- output influence was false;
- protected mutation dispatch was false.

### Rebuild identity

Two independent offline rebuild calculations produced the same descriptor digest. The
proof pinned the frozen 107-point pilot collection, release, manifests, points artifact,
point-ID set, aggregate fingerprint, first-write receipt, vector contract, payload lane
and false authority flags.

The rebuild proof used no network, provider call, Qdrant read, Qdrant write/delete,
Source write, R2 mutation or pointer mutation.

### Rollback

Rollback remains immediate `lexical-only` operation and requires no candidate Runtime,
provider, Qdrant, Worker, Queue or Explorer dependency. Production retrieval never left
lexical mode, so no production configuration mutation was required or performed.

## Phase decision

M23.7.6 implementation and reconciliation are complete. M23.7.7 may begin after this
reconciliation merges and issue #446 closes completed.

M23.7.7 must preserve both carry-forward blockers and must not claim semantic retrieval
is eligible for production or candidate-mode exposure. The final decision remains owned
by M23.7.8.

## Authority boundary

Source PR #19 remains open, draft and unmerged at
`deb3ad1e631c2149183d10561fbceb0a1848a989`.

No live traffic, user sampling, production query mirroring, answer serving, deployment,
production pointer, R2 mutation, Source mutation, Qdrant write/delete, Worker/Queue
mutation, public Graph Explorer, permanent ledger mutation, credential rotation,
promotion decision or Graph Neural Retrieval was dispatched.

Production mutation dispatched: false.
