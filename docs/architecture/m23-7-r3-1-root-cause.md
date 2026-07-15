# M23.7-R3.1 Retrieval-Quality Root-Cause Diagnostics

## Boundary

This workstream diagnoses the accepted R3 rejection. It does not repair the compiler, mutate Qdrant, change the production pointer, write R2, merge Source PR #19, enable semantic serving, relax thresholds or grant promotion eligibility.

Production retrieval remains `lexical`; `blocked_pending_retrieval_quality` remains open.

## Frozen entry

- Engine main: `a4be8373a03ac127cd1c8c99af450a2f78230cc0`
- Parent issue: `#474`, open
- R3.1 issue: `#478`, open
- R3 receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`
- Qdrant collection: `llm_wiki_m23_pilot_bge_m3_1024`, 107 points, named vector `default`, dimension 1024, Cosine

## Phase A and B finding

The accepted R1 compiler derives a semantic topic only from humanised payload identifiers. Numeric part and chunk coordinates are removed, and two-character language identifiers are discarded. The eight accepted R3 targets therefore reduce to the same normalised token set: `harness`, `theory`, `chunk`, `part`.

R3.1 adds a text-only query digest. The accepted compiler digest includes `probe_id`, so byte-identical query strings receive different compiler digests. Eight unique compiler digests therefore do not prove eight unique queries.

The accepted redacted R3 evidence also contains four exact same-class ranking pairs:

- direct-fact: probes 01 and 05;
- terminology: probes 02 and 06;
- cross-section: probes 03 and 07;
- provenance: probes 04 and 08.

The preliminary diagnosis confirms `identifier_humanisation_query_collision` from query identity and top-three ranking evidence. It remains deliberately unsealed until Phase C completes the read-only vector and payload diagnostics.

## Phase C remaining evidence

The final operator run must bind:

1. all 107 stored point vectors and payload identities;
2. eight fresh BGE-M3 query vectors in exact probe order;
3. the full accepted R3 top-10 cases;
4. the exact accepted R3 receipt SHA-256.

It must calculate target cosine, top cosine, margin, full-corpus target rank, point and query norm error, centroid and hub frequency, and reproduce the receipt ranking locally with cosine scoring.

No raw query, answer, service URL, hostname or credential may be persisted.

## Exit

R3.1 remains open after this Phase A/B implementation. Issue `#474` also remains open. A repair proposal is forbidden in this diagnostic PR and must use a later, separately governed workstream after the vector evidence seals the root-cause report.
