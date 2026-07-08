# M11 Knowledge Compiler Architecture

## 1. Purpose

The Knowledge Compiler converts immutable, admitted M10 evidence into reviewer-facing curation proposals. It is a build-plane component between source intake and human-governed canonical Source publication.

It does not decide truth by itself. It preserves evidence, classifies uncertainty, detects conflicts, proposes Source changes, and stops at a review boundary.

## 2. Trust boundaries

### Trusted inputs

The compiler trusts identity and integrity only after verifying:

- an immutable `intake-snapshot/v1` envelope;
- an immutable normalized derivative and derivative record;
- an accepted compilation-admission result;
- exact object hashes;
- connector and normalizer identities;
- resolved owner, license, audience, and access-policy evidence;
- no audience or policy broadening between snapshot and derivative.

Source content remains untrusted data. Prompt-like text inside evidence is never executable instruction.

### Untrusted inputs

- source prose and embedded instructions;
- provider or model output;
- confidence values;
- inferred entities, concepts, claims, relationships, dates, and citations;
- proposed matches against canonical Source;
- user-supplied target paths or identifiers not revalidated by the compiler.

### Trusted decisions

Only a separate immutable human decision may authorize a Source proposal to become a Source PR package. The compiler itself never grants canonical-write permission.

## 3. Planes and ownership

### Intake plane, M10

Owns acquisition, immutable raw bytes, snapshot envelopes, normalized derivatives, connector evidence, typed rejection/quarantine, and compilation admission.

### Compiler plane, M11

Owns deterministic structuring, source maps, extraction candidates, resolution proposals, synthesis proposals, validation reports, and reviewer packets.

### Canonical Source plane

Owns reviewed concept pages, entity pages, comparison pages, provenance, registries, contradiction/supersession records, and Source PR history.

### Runtime plane

Owns derived release bundles, sections, graph, indexes, source maps, runtime query, citations, and audience filtering. Runtime artifacts are never edited as truth.

## 4. Compiler stages

### Admit

Load the exact snapshot, derivative, admission evidence, and effective policy. Verify identities, hashes, schema versions, object-key namespaces, and non-broadening policy.

### Structure

Parse normalized evidence into deterministic blocks such as headings, paragraphs, lists, list items, code, tables, quotations, and metadata. Each block receives a stable ID and one or more exact source-map segments.

### Extract

Emit bounded candidates for:

- entity;
- concept;
- claim;
- definition;
- decision;
- date;
- relationship;
- citation.

Each candidate must cite one or more exact source-map segments. Candidates lacking evidence are rejected before resolution.

### Resolve

Compare extraction candidates with an exact clean canonical Source snapshot and emit one explicit outcome:

- `new_concept`;
- `existing_concept_update`;
- `alias`;
- `duplicate`;
- `contradiction`;
- `supersession`;
- `unresolved_conflict`;
- `rejected_unsupported_claim`.

Heuristics may nominate candidates but cannot silently merge, overwrite, or discard knowledge.

### Synthesize

Create reviewer-facing proposals for concept pages, comparison pages, entity pages, index changes, citation changes, relationship changes, or Source patches. A synthesis proposal may contain only accepted evidence-bound candidates and must retain resolution identities.

### Validate

Validate schema, stable IDs, links, citations, provenance, evidence coverage, duplicate handling, contradiction handling, supersession basis, unsupported-claim rejection, ACL/license propagation, private-data risk, target-path safety, and absence of orphan candidates or proposals.

### Review ready

Package immutable artifacts and a deterministic manifest. Set all write permissions to false. Hand the packet to a separate human-review workflow.

## 5. Identity model

M10 canonical JSON v1, NFC normalization, sorted keys, and SHA-256 remain the identity foundation.

```text
compiler_run_id = crun_<sha256(compiler input + compiler identity)>
block_id        = block_<sha256(run ID + ordinal + kind + text + source map)>
source_map_id   = smap_<sha256(run ID + ordered source segments)>
candidate_id    = cand_<sha256(run ID + candidate type + value + evidence refs)>
resolution_id   = cres_<sha256(Source identity + candidate + outcome + evidence)>
proposal_id     = prop_<sha256(run ID + ordered resolutions + target + content)>
```

Timestamps, actor display names, and operational retry counters do not enter semantic artifact identity unless the contract explicitly marks them as identity-bearing.

## 6. Object layout

```text
compiler/v1/runs/{compiler_run_id}/input.json
compiler/v1/runs/{compiler_run_id}/run-record.json
compiler/v1/runs/{compiler_run_id}/events/{ordinal}-{event_hash}.json
compiler/v1/runs/{compiler_run_id}/structured/blocks.json
compiler/v1/runs/{compiler_run_id}/structured/source-map.json
compiler/v1/runs/{compiler_run_id}/extraction/candidates.json
compiler/v1/runs/{compiler_run_id}/resolution/resolutions.json
compiler/v1/runs/{compiler_run_id}/synthesis/proposals.json
compiler/v1/runs/{compiler_run_id}/validation/report.json
compiler/v1/runs/{compiler_run_id}/review/packet-manifest.json
compiler/v1/runs/{compiler_run_id}/result.json
compiler/v1/rejections/{compiler_run_id}.json
```

All run artifacts are immutable. Optional queue, cursor, or source-head projections are rebuildable and must use compare-and-swap. They are not evidence and do not determine truth.

## 7. Policy propagation

The effective audience is the most restrictive audience among the snapshot, derivative, admission, relevant canonical target, and reviewer-approved policy.

```text
public < internal < confidential < restricted
```

A compiler stage may preserve or increase restriction. It may never reduce restriction. Principal sets use intersection or a more restrictive policy, never union-based broadening. Unresolved policy remains restricted and cannot produce a public proposal.

License and owner evidence are copied by exact reference and hash. An unresolved or incompatible license blocks synthesis or places the run into a typed review state. It cannot be replaced by a model guess.

## 8. Evidence continuity

Every candidate and proposal must be traceable through:

```text
proposal
→ resolution
→ extraction candidate
→ structured block
→ source-map segment
→ normalized derivative
→ immutable snapshot
→ raw content hash and connector evidence
```

A missing link is a release-blocking compiler validation failure.

## 9. Provider boundary

M11.1 and M11.2 require no model. Later provider-backed extraction or synthesis must use a closed prompt envelope, no tools or network unless separately governed, explicit provider/model/harness identity, strict output schemas, exact evidence validation, and unsupported-claim quarantine. Provider output is never written directly to Source.

## 10. Failure model

Failures are typed by stage:

- input identity or hash mismatch;
- admission missing or rejected;
- ACL/license unresolved or broadened;
- unsupported normalized media type;
- malformed structure;
- evidence span mismatch;
- extraction limit exceeded;
- ambiguous duplicate;
- contradiction requiring review;
- supersession without basis;
- unsupported claim;
- unsafe Source target;
- validation failure;
- immutable collision.

Pre-run failures produce sanitized rejection evidence without pretending a run completed. Post-admission failures retain already-verified evidence and end in a typed terminal state.

## 11. M11.2 executable boundary

The first implementation accepts only an admitted local Markdown derivative produced by M10 `local_file` and `markdown/1.0.0`. It deterministically structures Markdown and emits bounded candidates using explicit rules. It performs no Source lookup, model call, synthesis, GitHub write, candidate build, release operation, production mutation, or ledger append.