# M23.7 Repair R1: Live Probe Semantic Alignment

Implementation issue: #460. Parent decision: #455.

## Purpose

R1 repairs the semantic meaning of the bounded live probes used by M23.7.5. The old
runner embedded each sampled `section_id` as the query text. That measured identifier
string similarity rather than a held-out retrieval intent and produced an accepted live
overlap@5 result of 0.25 with drift -0.70.

R1 does not rerun the provider or Qdrant. It creates the versioned compiler and evidence
contract that R3 must use when it later binds real pilot samples and performs a new
privacy-safe bounded live observation.

## Probe contract

The manifest contains eight positive, ACL-allowed held-out slots:

- two `direct-fact` slots;
- two `terminology` slots;
- two `cross-section` slots;
- two `provenance` slots.

The slots preserve their M23.7.1/M23.7.2 case identities. At R3 runtime, exactly eight
public non-production samples are sorted by point ID and bound to the slots in order.
The exact target `section_id` becomes the expected relevance set for that live probe.

The query compiler humanises identifiers in this priority order:

1. `concept_id`;
2. `section_id`;
3. `article_id`;
4. `document_id`;
5. `source_path`.

Generic identifier tokens, numeric suffixes, long hexadecimal fragments and file
extensions are removed. The remaining topic must contain at least three semantic tokens.
A class-specific template then produces the ephemeral synthetic query.

## Privacy and evidence

Compiled raw query text exists only in memory while the plan is built. Durable evidence
contains:

- probe ID;
- offline case ID and query class;
- point and target section IDs;
- exact expected relevance set;
- query digest;
- semantic token count;
- query character count.

No raw query or answer text is committed. No user query is used. The manifest forbids
arbitrary free text and direct reuse of a raw `section_id` as the query.

## Deterministic evidence

- manifest:
  `pilot/m23/m23-7-r1-semantic-alignment-manifest.json`;
- manifest SHA-256:
  `ebff335d572461f4438ed06c4cc35288b0d0def8bbfc2b51e80bb262db12c576`;
- fixture report:
  `pilot/m23/m23-7-r1-semantic-alignment-report.json`;
- report SHA-256:
  `7ee8ddf6bf955cf0c1a10dd5442aa60d0b4b791bc2f3f4deba386213adf815e1`.

The fixture report proves deterministic slot binding, query compilation, digesting,
redaction and expected-relevance construction. It does not claim the fixture targets are
the live pilot targets.

## Exit semantics

R1 completes when the manifest, compiler, redacted mapping report, adversarial tests and
exact-head CI pass and an independent reconciliation merges.

R1 completion means:

- the runtime compiler is ready for R3 live binding;
- the raw-section-ID query defect is removed from the future observation contract;
- live target binding remains pending R3;
- `blocked_pending_retrieval_quality` remains open;
- `blocked_pending_latency` remains open;
- R2 and R3 remain required;
- promotion eligibility remains false.

## Authority boundary

Production retrieval remains lexical. Candidate mode is disabled. Source PR #19 remains
open, draft and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

No live traffic, user sampling, provider call, Qdrant read/write/delete, deployment,
production pointer, R2 mutation, Source mutation, Source PR merge, Worker/Queue mutation,
public Graph Explorer, permanent ledger mutation, credential rotation, promotion or
Graph Neural Retrieval is dispatched.

Production mutation dispatched: false.
