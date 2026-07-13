# M21.3 evidence-bound entity and concept candidate extraction

## Status

Implementation contract for issue #319. M21.3 converts validated M21.2 intake evidence into deterministic, bounded, review-only extraction candidates. It performs no model, provider, network, Source, candidate-release, or production action.

## Input authority

The builder accepts only:

- `knowledge-engine-resumable-batch/v1` plans with valid digests;
- `knowledge-engine-batch-checkpoint/v1` checkpoints bound to the exact plan and repository identity;
- completed M21.2 items;
- caller-supplied `knowledge-engine-normalized-derivative/v1` evidence;
- caller-supplied extraction proposals;
- an explicit bounded controlled-tag allowlist.

Every derivative binds to the exact batch, item key, source-content digest, audience, language, and normalized-text digest. A derivative is not accepted while its M21.2 item remains pending, running, retryable, failed, or skipped.

## Candidate kinds

M21.3 emits review candidates for:

- concepts;
- entities;
- aliases;
- definitions;
- claims;
- bilingual terminology;
- potential duplicate hints;
- untyped relationship hints.

Concept and entity candidates may contain bounded definitions and aliases. Entity candidates require an entity type. Alias, definition, claim, bilingual-term, duplicate, and relationship hints retain the fields needed for later human review and M21.4/M21.5 processing.

Relationship hints intentionally contain `ontology_type: null`. M21.3 rejects caller-supplied `relation_type`; only M21.4 may map evidence into approved ontology types.

## Exact evidence spans

Every candidate must contain one to sixteen exact normalized evidence spans. A span records:

- M21.1 inventory snapshot identity;
- M21.2 plan digest;
- derivative ID;
- start and end offsets;
- SHA-256 of the exact normalized excerpt.

Offsets must be integer, in bounds, non-empty, and unique within the candidate. The excerpt itself is not copied into candidate output. Digest or text drift fails closed.

## Determinism

The builder applies Unicode NFKC normalization and deterministic whitespace folding to candidate fields. Aliases, tags, evidence spans, and candidates use stable sorting. Candidate IDs are derived from the exact plan identity, normalized candidate payload, and evidence spans.

Identical proposals would create the same candidate ID and therefore fail as duplicates rather than being silently collapsed.

## Bounds

The contract permits at most:

- 100 normalized derivatives;
- 1,000 proposals;
- 1,000,000 characters per derivative;
- 16 evidence spans per candidate;
- 32 aliases per candidate;
- 16 controlled tags per candidate;
- 200 allowlisted controlled tags;
- 200 characters per label;
- 4,000 characters per definition or claim body.

Confidence is advisory evidence in the inclusive range zero to one. High confidence never grants canonical authority.

## Security and authority

Source text is explicitly marked untrusted. Prompt-like text is treated only as inert evidence and is never executed. Candidate payloads reject secret-like material and authority-escalation fields such as canonical, approved, production-authority, Source-write, tool-call, system-prompt, or typed-relation claims.

Every packet and candidate declares:

- `authority: candidate_only`;
- `canonical_knowledge: false`;
- `production_authority: false`;
- `status: pending_review` at candidate level;
- `review_required: true` at packet level.

Controlled tags must come from the explicit allowlist. Bilingual terms must use distinct valid language identifiers. Duplicate hints and relation hints cannot self-reference.

## Acceptance

Acceptance covers:

- deterministic packet and candidate IDs;
- all supported candidate kinds;
- exact evidence offsets and excerpt digests;
- M21.2 plan/checkpoint identity binding;
- completed-item enforcement;
- derivative source, audience, and text-digest validation;
- controlled-tag allowlisting;
- bilingual terminology constraints;
- duplicate-candidate and duplicate-derivative rejection;
- secret and authority-escalation rejection;
- prompt-injection isolation;
- M20, M21.1, and M21.2 regressions.

## Exclusions

No embedding, LLM, provider, network, live connector, scheduler, queue, worker, Source edit, canonical adoption, typed ontology relationship creation, entity resolution, bulk Source PR, candidate or production publication, production pointer, retained R2 object, credentials, permanent ledger, rollback, M21.4 work, cross-release merge, or Graph Neural Retrieval is included.
