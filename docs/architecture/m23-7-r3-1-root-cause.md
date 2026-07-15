# M23.7-R3.1 Retrieval-Quality Root-Cause Diagnostics

## Boundary

This workstream diagnoses the accepted R3 rejection. It does not repair the compiler, mutate Qdrant, change the production pointer, write R2, merge Source PR #19, enable semantic serving, relax thresholds or grant promotion eligibility.

Production retrieval remains `lexical`; `blocked_pending_retrieval_quality` remains open.

## Frozen entry

- Engine main: `a4be8373a03ac127cd1c8c99af450a2f78230cc0`
- Diagnostic implementation head: `a2e963df9a0b74de7220cc477946f25001b3a9cd`
- Parent issue: `#474`, open
- R3.1 issue: `#478`, open until merge and independent reconciliation
- R3 receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`
- Operator-result canonical SHA-256: `5a3d950142ae85cc27997326b894ed8cce338918370dcd8ff94474300476dc2a`
- Final root-cause report SHA-256: `10a5bd0aa1b141cb508db8781269d2d47ed1cf9309a3065671f3356f7e1d5f7c`
- Qdrant collection: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points, named vector `default`, dimension 1024, Cosine

## Phase A and B finding

The accepted R1 compiler derives a semantic topic only from humanised payload identifiers. Numeric part and chunk coordinates are removed, and two-character language identifiers are discarded. The eight accepted R3 targets therefore reduce to the same normalised identifier surface.

R3.1 adds a text-only query digest. The accepted compiler digest includes `probe_id`, so byte-identical query strings receive different compiler digests. Eight unique compiler digests therefore do not prove eight unique queries.

The eight probes collapse to four exact same-class query identities:

- direct-fact: probes 01 and 05;
- terminology: probes 02 and 06;
- cross-section: probes 03 and 07;
- provenance: probes 04 and 08.

## Phase C read-only vector seal

The operator run bound the accepted R3 receipt to all 107 stored payload identities and vectors, generated eight fresh BGE-M3 query vectors, and replayed the full accepted top-ten rankings locally with cosine scoring.

Observed invariants:

- collection status `green`, 107 points, `default` vector, dimension 1024, Cosine;
- query-vector norm maximum error `0.0`;
- point-vector norm maximum error `1.1353e-08`;
- all eight accepted receipt rankings exactly match local full-corpus cosine replay;
- target ranks are `24, 96, 17, 83, 64, 4, 56, 7`;
- two corpus sections occur in the top ten for all eight probes;
- maximum top-ten hub frequency is `8`.

These observations exclude a top-k transport defect and a batch-order mapping defect. They do not show a Qdrant scoring failure, vector-normalisation failure, or receipt drift.

## Final hypothesis disposition

- H1 identifier humanisation query collision: **confirmed primary**.
- H2 prefix or normalisation mismatch: **not supported as causal**.
- H3 vector and payload binding error: **not supported as causal**.
- H4 corpus hubness: **confirmed compounding**.
- H5 multilingual alignment failure: **not supported as primary**.
- H6 target-label validity error: **not supported as causal**.
- H7 top-k request defect: **ruled out**.
- H8 batch mapping defect: **ruled out**.

The primary failure occurs before retrieval: different target sections are compiled into byte-identical semantic queries. Corpus hubness then amplifies the collapse by repeatedly elevating generic Part 01 sections.

## Authority and privacy

The diagnostic performed three Qdrant reads and zero Qdrant writes. It did not persist raw queries, raw answers, service URLs, hostnames or credentials. It did not dispatch protected mutations or grant promotion eligibility.

## Exit

R3.1 root-cause diagnosis is sealed, but closure is procedural rather than promotional:

- PR `#482` must pass exact-head CI and merge with expected-head protection;
- an independent reconciliation PR must bind the merge SHA and pass exact-head CI;
- issue `#478` may close only after that reconciliation merges;
- parent issue `#474` remains open;
- production retrieval remains lexical;
- `blocked_pending_retrieval_quality` remains active;
- the next legal workstream is a separately governed repair proposal. No repair is included in this diagnostic PR.
