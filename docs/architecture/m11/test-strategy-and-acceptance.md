# M11 Test Strategy and Acceptance

## 1. M11.1 architecture tests

Repository tests must verify:

- all six schemas parse as JSON;
- every schema uses Draft 2020-12, a stable `$id`, an exact schema-version constant, and closed top-level objects;
- compiler input requires exact snapshot, derivative, admission, policy, and compiler identities;
- structured blocks require exact ordered source-map references;
- extraction candidates require non-empty evidence and cannot self-authorize;
- resolution outcomes exactly match the M11 taxonomy;
- duplicate and contradiction are separate outcomes;
- supersession requires a target and basis;
- unsupported-claim rejection cannot be synthesis-eligible;
- synthesis proposals require resolution and evidence references and remain review-only;
- the example input is internally consistent;
- architecture documents pin M10 and M5 reuse rather than creating parallel storage or review systems;
- production, canonical Source, candidate, release, GitHub governance, and permanent-ledger writes are forbidden.

No new schema-validation dependency is required for M11.1. Tests validate the contract structure and the supplied example with the Python standard library. M11.2 may add a bounded runtime validator or an existing approved dependency only in a separate reviewed change.

## 2. M11.2 deterministic reference tests

The local Markdown reference compiler must cover:

### Accepted path

- exact immutable M10 snapshot and derivative lookup;
- exact SHA-256 verification of every referenced object;
- accepted compilation admission;
- local-file connector and Markdown normalizer identity;
- deterministic heading, paragraph, list, list-item, code, quotation, and metadata blocks where present;
- stable block ordering and IDs;
- exact normalized-character offsets and line ranges;
- bounded deterministic extraction candidates;
- owner, license, audience, and access-policy propagation;
- immutable events and terminal result;
- local reviewer artifact materialization;
- exact replay idempotency.

### Integrity failures

- missing snapshot, derivative, admission, or normalized object;
- wrong object hash;
- identity mismatch;
- malformed or unsupported schema version;
- rejected or quarantined admission;
- source/derivative policy mismatch;
- unsupported connector or normalizer;
- invalid UTF-8 or unsupported normalized media type;
- source-map offset drift;
- immutable collision;
- event-chain tamper;
- structure or candidate limit exceeded.

### Security boundaries

- unresolved ACL/license cannot produce a public review artifact;
- audience or principal-set broadening is rejected;
- secret-like source cannot re-enter after M10 rejection;
- prompt-like content remains data and cannot alter compiler configuration;
- arbitrary local paths are not accepted as compiler input;
- no network, subprocess, database, Source, GitHub governance, candidate, release, production, or ledger mutation surface is imported or invoked;
- output keys remain under `compiler/v1/`.

## 3. Later M11 stage tests

### Extraction

- exact evidence required for every accepted candidate;
- duplicate candidate IDs rejected;
- unknown fields rejected;
- unsupported statements quarantined;
- provider identity and closed harness recorded when models are used;
- deterministic replay and bounded output.

### Resolution

- exact clean Source SHA and snapshot required;
- new concept, update, alias, duplicate, contradiction, supersession, unresolved conflict, and unsupported rejection fixtures;
- ambiguity fails closed;
- destructive or policy-changing outcomes require review;
- multilingual title/alias/content fixtures;
- claim-level provenance retained.

### Synthesis and validation

- only eligible resolution outcomes enter proposals;
- rejected unsupported claims never appear in proposal content;
- every proposal statement has evidence coverage;
- stable IDs and safe target paths;
- citation targets exist;
- no orphan candidate, resolution, or proposal;
- ACL/license/owner propagation;
- private-data and secret scan;
- deterministic packet manifest;
- direct write permissions remain false.

### Review and Source package

- exact packet-bound immutable decisions;
- partial approval identity;
- contradiction/supersession acknowledgement;
- target drift rejection;
- clean Source revalidation;
- stable ID preservation;
- no direct apply;
- Source validation and human PR review required.

## 4. Regression gates

Each executable M11 slice must preserve:

- all M10 connector and closure tests;
- historical M5 synthesis, resolution, and review tests;
- M7-M9 governance and lifecycle tests;
- reference vertical slice;
- container build;
- R2 canary;
- isolated release integration and cleanup;
- read-only verification of the unchanged M9 production pointer where the workflow is applicable.

A green workflow is necessary but not sufficient. Artifacts, exact identities, permissions, object namespaces, and production invariants must be inspected.

## 5. M11.1 exit criteria

- parent #146 and architecture issue #147 exist;
- architecture branch starts at exact M10 closure SHA;
- all required documents, schemas, and example are present;
- contract tests pass at the final reviewed head;
- no runtime or workflow mutation surface is added;
- no Source, candidate, release, production, or permanent-ledger mutation occurs;
- M11.2 can be implemented from repository contracts alone;
- #147 closes only after merge and evidence inspection;
- #146 remains open;
- #30 remains open.

## 6. M11 milestone exit criteria

M11 closes only after a real admitted source can move through structure, extraction, resolution, synthesis, validation, human review, and Source PR packaging while preserving exact evidence, policy, deterministic replay, and production separation. M12 runtime evaluation work does not begin as a substitute for incomplete compiler behavior.