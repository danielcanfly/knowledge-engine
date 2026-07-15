# M23.7 Repair R3 Bounded Live Retrieval-Quality Re-observation

Issue: #474. Parent repair decision: #455.

## Purpose

R3 is the final repair workstream created by the M23.7.8 `repair` decision. It repeats the bounded live retrieval observation only after R1 corrected probe semantics and R2 qualified a sub-1200 ms regional execution path.

The previous M23.7.5 overlap@5 result of `0.25` and drift of `-0.70` remains valid historical evidence for the old placeholder-aligned observation. It is not reused as the R3 quality oracle because R1 proved that the raw placeholder section identifier was not a semantically aligned query.

## Frozen entry identities

- engine main: `5870e4dd3d10076ef7d35a1eb485b358179d9305`;
- repair handoff: `7fb6fadf91f1a09110bf1d0e653652f52a298ebc0119aee3743180314e16f0b9`;
- R1 manifest: `ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576`;
- R1 report: `7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1`;
- R2.1 live receipt: `aa56655d19cb617177bd8e4708c02e1cd6ce02189fcfee32a5b397ef0eba67db`;
- M23.7.1 quality contract: `7dbaca446fa7a7eccd5f072ab71ffaa8bd601ba8c3140afae3d80d81ce0ad8c1`;
- M23.7.2 offline evaluation: `9d39f4c90392a0ae56f758b26b7b080bd03872aa1ccce596e8762087896f08ce`;
- R3 contract: `44177964da873958f1d433aab719725ff622f050bd7e96ec086cc8e06aa0f412`;
- deterministic fixture report: `9bdd7404907e532530dc277051c8d4347bc4cf03290f76c538624aaf05154338`.

The accepted implementation scope is required to pass Ruff, Python adversarial tests, Worker unit tests, deterministic replay and privacy-authority scans at the same exact PR head.

## Execution path

The operator samples exactly eight public, evaluation-only Qdrant points through the accepted strict-mode-safe read client. R1 deterministically compiles the same eight semantic probes and binds each probe to one exact target section.

A transient, bearer-protected Cloudflare Worker is placed near the configured Qdrant endpoint. It performs:

1. two read-only collection identity snapshots;
2. one Workers AI binding call to `@cf/baai/bge-m3` for all eight probes;
3. one Qdrant `/points/query/batch` call with named vector `default`, top 10, payloads enabled and vectors disabled.

The generated `wrangler.local.jsonc`, placement hostname, Qdrant URL, Qdrant key and operator token are never committed. Worker invocation logging is disabled. The response contains only digests, target and ranked section IDs, bounded timings, collection identities and authority flags.

## Frozen gates

A real R3 receipt passes only when all gates are true:

- Recall@5 is at least `0.82`;
- MRR@10 is at least `0.68`;
- nDCG@10 is at least `0.72`;
- Worker-internal provider plus Qdrant shadow time is at most `1200 ms`;
- error rate is exactly `0`;
- ACL violation rate is exactly `0`;
- output influence rate is exactly `0`;
- collection identity is unchanged;
- exactly one Workers AI binding call and one Qdrant batch query occur;
- Qdrant writes remain zero.

The fixture report passes these gates only to prove deterministic implementation shape. It is not live acceptance evidence.

## Exit semantics

The live operator command always writes a redacted receipt. Its status is exactly one of:

- `pass_bounded_live_reobservation`;
- `rejected_bounded_live_reobservation`.

`blocked_pending_retrieval_quality` is cleared only by a passing live receipt, exact-head CI, expected-head merge and independent reconciliation. A rejection preserves the blocker and does not weaken any threshold.

Even after an R3 pass, promotion eligibility remains false. All repair blockers being cleared permits a new explicit promotion decision; it does not itself promote the candidate.

The transient Worker must remain available through accepted reconciliation, then be deleted and independently proven absent before #474 closes.

## Authority boundary

Production retrieval remains lexical. Candidate mode, semantic answer serving and production authority remain disabled. Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

No production pointer, R2 object, Source mutation, Source PR merge, Qdrant write/delete, permanent ledger, public Graph Explorer, user traffic, answer serving, promotion or Graph Neural Retrieval is authorised.

Production mutation dispatched: false.
