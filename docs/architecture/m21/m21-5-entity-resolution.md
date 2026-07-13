# M21.5 deterministic entity resolution and contradiction evidence

## Status

Implementation contract for issue #325. M21.5 consumes the exact M21.3 extraction packet, exact M21.4 governed packet, an immutable reviewed Source resolution index, and a bounded candidate-audience envelope. It emits deterministic review evidence only. It does not modify Source, approve a candidate, create a Source pull request, or publish candidate or production state.

## Pinned authority

M21.5 pins:

- Source commit `a6ba738d910d01d2ae99b1968f0831989934c549`;
- Foundation commit `e5ef644053d34e89c70d2ceb37521e1c59234832`;
- the exact Engine, Source, and Foundation identity carried by M21.3 and M21.4;
- the exact M21.4 `extraction_packet_sha256` binding to M21.3.

Every input packet is verified against canonical JSON SHA-256 before its contents are used. Cross-release packet mixing fails closed.

## Source resolution index

The caller supplies `knowledge-engine-source-resolution-index/v1`. It contains only reviewed identity fields required for matching:

- immutable `x_kos_id`;
- concept path;
- title and normalized title;
- approved concept aliases;
- governed bilingual terms;
- canonical tags as weak metadata;
- audience/ACL identity;
- Source file digest.

The index is bound to the pinned Source and Foundation SHAs and signed with `index_sha256`. Immutable IDs and paths must be unique after Unicode normalization. Approved aliases have one owner and may not collide with another concept's canonical title. Duplicate normalized titles and bilingual ownership collisions remain representable so a candidate can become `ambiguous` rather than being silently merged.

Renderer state, writable handles, unpublished reviewer notes, provider credentials, and secrets are forbidden.

## Candidate audience envelope

M21.3 evidence spans do not carry a complete ACL field. M21.5 therefore requires a bounded `candidate_audiences` mapping whose keys exactly cover the M21.3 candidate IDs and whose values are `public`, `internal`, or `restricted`.

The mapping is evidence metadata, not canonical knowledge. Its canonical digest is stored as `candidate_audience_sha256`. A candidate-to-Source audience mismatch becomes a review-only `reject`; it never crosses the ACL boundary.

## Conservative normalization and strong signals

Matching uses Unicode NFKC, whitespace collapse, and case folding. It does not use probabilistic translation, edit distance, embeddings, or fuzzy automatic merge.

The only strong Source signals are:

1. exact normalized `x_kos_id`;
2. exact normalized concept path;
3. unique exact normalized title;
4. exact approved alias ownership;
5. unique exact bilingual term ownership.

If strong signals resolve to more than one Source concept, the result is `ambiguous`. Confidence cannot break the tie. If a unique target has an incompatible audience, the result is `reject`.

## Weak signals and within-batch dedupe

Governed tags from M21.4 are weak metadata only. Shared tags may produce `probable_duplicate`, but never `exact_existing_match`. Typed relation similarity is validated as part of the exact M21.4 packet and deliberately ignored as a merge signal.

Within one exact M21.3 packet, endpoint candidates are clustered only by deterministic explicit evidence:

- the same exact normalized candidate label; or
- an explicit M21.3 `duplicate_hint` connecting two candidate names.

Cluster IDs bind the exact M21.3 packet digest and sorted member IDs. A cluster cannot span candidate audiences. Cross-audience collisions become blocking `reject` records.

## Alias handling

Concept aliases and tag aliases remain separate domains. M21.5 never converts a governed tag alias into a concept alias.

An alias candidate must resolve its target to exactly one reviewed Source concept, either directly through Source identity fields or through an exact endpoint resolution from the same packet. The proposed alias must not be owned by another concept or equal another concept's canonical title. Alias-to-alias targets are rejected as forbidden alias chains.

A valid new alias produces `attach_alias_candidate`. An already approved alias produces `exact_existing_match`. Both remain `pending_review`; neither mutates Source.

## Contradiction evidence

M21.3 claim bodies are untrusted text and do not contain governed predicate, polarity, or scope fields. M21.5 therefore accepts an optional bounded `claim_assertions` envelope. Each assertion is bound to one exact M21.3 claim candidate and contains:

- normalized predicate or claim key;
- bounded scope/context fields;
- positive or negative polarity;
- optional normalized value.

The envelope digest is stored as `claim_assertions_sha256`. A contradiction candidate is emitted only when two claims have:

- the same uniquely resolved Source subject;
- the same normalized predicate;
- the same exact bounded scope;
- opposite polarity or incompatible normalized values;
- exact M21.3 evidence spans on both sides.

Different scope or context is not a contradiction. Missing claims are not contradictions. Confidence never resolves a contradiction automatically.

## Output contract

The output schema is `knowledge-engine-resolution-candidates/v1`. Resolution records use only:

- `exact_existing_match`;
- `attach_alias_candidate`;
- `probable_duplicate`;
- `distinct_new_candidate`;
- `ambiguous`;
- `reject`.

Contradiction records declare `outcome: contradiction_candidate` in the packet's separate `contradictions` collection.

Every record preserves exact candidate IDs, evidence spans, audience, Source target identity when available, strong and weak signals, deterministic identity, pending-review state, and candidate-only authority. The packet binds the exact M21.3, M21.4, Source index, audience envelope, and claim-assertion digests.

`probable_duplicate`, `ambiguous`, `reject`, and every contradiction block M21.6 packaging. A clean `exact_existing_match`, `attach_alias_candidate`, or `distinct_new_candidate` does not bypass human review; it only means the M21.5 packet itself has no unresolved packaging blocker for that record.

## Bounds and deterministic replay

Initial bounds are:

- 1,000 M21.3 candidates;
- 10,000 Source concepts;
- 1,000 resolution records;
- 100 members per duplicate cluster;
- 1,000 contradiction records;
- 32 aliases, bilingual terms, or tags per Source concept;
- 16 exact evidence spans per candidate or governed record;
- 20 strong or weak signals per resolution;
- eight scope fields per claim assertion.

Canonical JSON, sorted candidates, sorted cluster members, sorted signals, and packet-bound IDs make deterministic replay byte-identical.

## Fail-closed cases

M21.5 rejects or blocks on:

- bad M21.3, M21.4, or Source index digest;
- packet identity or release mismatch;
- candidate, governed tag, or governed relation authority drift;
- duplicate candidate or governed record IDs;
- missing or malformed evidence;
- Source identity, alias ownership, or alias/title collision;
- Unicode-normalized immutable identity collision;
- candidate audience coverage or ACL mismatch;
- ambiguous Source title, alias, path, ID, or bilingual ownership;
- alias chain or alias ownership ambiguity;
- confidence outside the source candidate range;
- secret-like or unbounded payload;
- resolution or contradiction count overflow.

## Exclusions

No model/provider/network call, live connector, scheduler, queue, worker, Source edit, canonical adoption, review approval, bulk Source PR, candidate publication, production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.6 or later work, M22 multi-hop planner, cross-release merge, or Graph Neural Retrieval is included.

## Closure reconciliation

M21.5 implementation was delivered through issue #325 and implementation PR #326. The implementation PR merged only after the exact final head passed every required workflow and the changed-file, discussion, review, and thread audits were clean.

Exact identity chain:

- M21.4 reconciliation base: `a538abb62adccd5ca4494a4d43c07b8094c08337`;
- first bootstrap-only head: `9cd3f707c9390eb39b2eba9458a8baa2acf1284d`;
- corrected bootstrap-only head: `1100b19f306ba5918ac6341b202f6882d6a03179`;
- non-workflow materializer head: `3cfb4014e76fb62d1029da3421918ad16380b2fb`;
- transient materialized head: `0d7858658b3a88efc55b1fb4b5164f2dca844726`;
- bootstrap cleanup head: `fbc8ad7fe5944669e54f10614127c84765557108`;
- final implementation head: `2834bf63731db73fa5f1c2bbca1682bf9e9b130e`;
- implementation merge: `04eb8978b20b4ebcc4107e25b1bca4a081daf75a`.

The first bootstrap-only head restored the payload correctly but failed an over-strict temporary-path string assertion. The corrected bootstrap-only head again restored and validated the payload but could not push a commit that self-modified workflow files under the Actions token boundary. Neither head is acceptance evidence. The non-workflow materializer then committed the architecture document, implementation module, and tests without changing workflow files. The transient materialized and bootstrap-cleanup heads are also not acceptance evidence. The connector installed the final exact-head workflow, producing the sole accepted implementation head.

Implementation scope at the accepted head was exactly four added files:

- `.github/workflows/m21-5-entity-resolution.yml`;
- `docs/architecture/m21/m21-5-entity-resolution.md`;
- `src/knowledge_engine/m21_entity_resolution.py`;
- `tests/test_m21_5_entity_resolution.py`.

The accepted head passed:

- M21.5 Entity Resolution and Contradictions #1;
- CI #680;
- M17 Architecture Canon Acceptance #73;
- M18 Graph v2 acceptance #116;
- R2 Release Integration #467.

PR #326 had no conversation comments, submitted reviews, or unresolved review threads. The merge used expected head SHA `2834bf63731db73fa5f1c2bbca1682bf9e9b130e`.

Local pre-upload validation also passed 25 M21.5 tests, Ruff, and compileall. No Source mutation, review approval, canonical adoption, production or production-pointer change, R2 object change, credential use, permanent-ledger change, rollback change, M21.6 work, M22 work, cross-release merge, or Graph Neural Retrieval was dispatched. Production mutation dispatched: false.
