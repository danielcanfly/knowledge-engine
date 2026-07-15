# M23.7 R3 Live Re-observation Rejection

Issue: #474.

## Accepted rejection evidence

The bounded live R3 observation produced a valid redacted receipt after transient Cloudflare propagation inconsistencies. The operator independently recomputed the receipt digest and confirmed an exact match.

- receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`;
- status: `rejected_bounded_live_reobservation`;
- Cloudflare placement: `local-NRT`;
- accepted receipt attempt: 5;
- temporary 404 observed: true;
- temporary 401 observed: true;
- authenticated schema smoke observed: true.

The repository stores a digest-bound rejection record at `pilot/m23/m23-7-r3-live-rejection.json`. The complete redacted operator receipt remains on the operator host and is bound here by its verified SHA-256.

## Measured quality

- Recall@5: `0.125` against minimum `0.82`;
- MRR@10: `0.049107142857` against minimum `0.68`;
- nDCG@10: `0.095501236426` against minimum `0.72`.

All three retrieval-quality gates failed. The result is not close to the frozen acceptance boundary and must not be converted into a pass by threshold relaxation or repeated sampling.

## Measured latency

- Workers AI provider: `1177 ms`;
- Qdrant batch: `597 ms`;
- Worker-internal shadow: `1774 ms` against maximum `1200 ms`;
- operator round trip: `3735 ms`, informational only.

The Worker-internal shadow gate also failed. This does not reopen the already reconciled R2 latency workstream; it means this concrete R3 observation did not satisfy the combined R3 gate.

## Safety and authority

The observation preserved all strict-zero gates:

- error rate: `0`;
- ACL violation rate: `0`;
- output influence rate: `0`;
- Qdrant writes: `0`;
- one Workers AI binding call;
- one read-only Qdrant batch query;
- two read-only collection snapshots.

Production retrieval remains lexical. Candidate mode, semantic answer serving and production authority remain disabled. Promotion eligibility remains false. Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

## Exit state

R3 is not complete. `blocked_pending_retrieval_quality` remains. No repair blocker is cleared by this receipt.

The diagnostic Worker `knowledge-engine-m23-7-r3-observation` must remain available until this rejection is independently reconciled. It must then be deleted and proven absent before the rejection workstream is sealed.

The next legal engineering action is a separately governed root-cause repair. It must inspect the bound case rankings and query-target alignment from the operator receipt without changing the frozen thresholds or granting production authority.

Production mutation dispatched: false.
