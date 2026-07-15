# M23.7 R3 Live Rejection Reconciliation

Issue: #474.

## Accepted chain

The R3 implementation merged through PR #475 at `e9d35811b87f2b708c6a30bd9f603a6a5a06c2f1`. The valid rejected live receipt was then recorded through PR #476.

Accepted rejection identities:

- PR #476 exact head: `86695fb07f190b4fc7cdd02d9d0091bd7df7e257`;
- PR #476 merge: `8045d67492bb412e5c0531844723bb227c1b228a`;
- receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`;
- rejection record SHA-256: `79f27ecf68aa32e855f458e4e30a62932e0a2ea8bc1de522fa5869ed0d4a5ee5`.

## Exact-head workflow acceptance

PR #476 exact head passed:

- M23.7 Repair R3 Bounded Live Re-observation run `29444756029`;
- CI run `29444756102`;
- M17 Architecture Canon Acceptance run `29444756023`;
- M18 Graph v2 acceptance run `29444756106`.

All four runs concluded successfully before expected-head merge.

## Reconciled outcome

Failed gates:

- Recall@5: `0.125`;
- MRR@10: `0.049107142857`;
- nDCG@10: `0.095501236426`;
- Worker-internal shadow: `1774 ms`.

Passed gates:

- error rate: `0`;
- ACL violation rate: `0`;
- output influence rate: `0`.

The retrieval-quality blocker remains. R3 is not complete. No promotion or production authority is granted.

## Authority and lifecycle

Production retrieval remains lexical. Candidate mode and semantic answer serving remain disabled. Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

After this reconciliation merges, the isolated Worker `knowledge-engine-m23-7-r3-observation` must be deleted and proven absent. Issue #474 remains open after deletion because the rejected R3 workstream requires a separately governed root-cause repair.

The next legal workstream is `M23.7-R3.1 retrieval-quality root-cause repair`. It must inspect the digest-bound case rankings and target alignment without relaxing the frozen thresholds.

Production mutation dispatched: false.
