# M11.3 Extraction Validation and Source-Aware Resolution

Status: implementation candidate
Parent milestone: #146
Slice issue: #151
Engine baseline: `26aa055b7eec30296675962f26513c99587d6ba8`
Canonical Source baseline: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`

## Purpose

M11.3 consumes one completed M11.2 compiler run, validates its complete evidence chain, compares the validated candidates with an exact clean canonical Source checkout, and emits deterministic review-only resolution artifacts.

It does not synthesize a Source patch, record a human decision, modify Source, create a pull request, build a candidate, publish a release, mutate production, or append the permanent production ledger.

## Validation boundary

Before resolution, the implementation verifies:

- the exact compiler run, input, block set, source-map set, candidate set, result, and adjacent event chain;
- exact M10 snapshot, derivative, admission, and normalized-object hashes referenced by compiler input;
- stable block, source-map, and extraction-candidate identities;
- exact normalized character offsets, line ranges, quotations, and quotation hashes;
- candidate-to-block-to-source-map evidence continuity;
- unsupported-candidate and synthesis-eligibility invariants;
- audience and access-policy non-broadening;
- all canonical-write permissions remain false.

A missing, malformed, or tampered evidence link produces immutable typed rejection evidence. Resolution never proceeds on partially trusted compiler output.

## Canonical Source boundary

The resolver accepts only repository `danielcanfly/knowledge-source` at an exact lowercase commit SHA. The checkout must be clean, all relevant `bundle` records must be tracked, and symlinks are rejected.

Concept pages require valid YAML front matter with:

- a stable `x-kos-id`;
- a non-empty title;
- valid aliases;
- a valid `x-kos-audience`;
- text description and Markdown body.

Duplicate concept IDs, titles, or aliases fail closed. The Source snapshot digest covers tracked Markdown, JSON, YAML, and YML files under `bundle` and is recorded with every resolution batch.

## Resolution taxonomy

Each candidate receives exactly one outcome:

```text
new_concept
existing_concept_update
alias
duplicate
contradiction
supersession
unresolved_conflict
rejected_unsupported_claim
```

The deterministic rules are deliberately conservative:

- exact alias identity may produce `alias`;
- exact title identity or one strong target with new evidence may produce `existing_concept_update`;
- exact Source representation may produce `duplicate`;
- explicit polarity conflict plus strong subject overlap may produce `contradiction`;
- an explicit `Supersedes:` or `Replaces:` marker with one exact target and a basis may produce `supersession`;
- no viable Source target may produce `new_concept`;
- multiple viable targets, ambiguous destructive matches, or standalone date/citation candidates produce `unresolved_conflict`;
- unsupported candidates produce `rejected_unsupported_claim`.

Similarity is stored only as a match observation. A fuzzy score alone cannot establish duplicate, contradiction, or supersession and can never silently merge canonical knowledge.

## Policy propagation

The effective resolution audience is the most restrictive audience among compiler input, candidate, and matched Source targets:

```text
public < internal < confidential < restricted
```

Resolution may preserve or increase restriction, never reduce it. All Source, GitHub, and production write permissions remain false.

## Immutable output layout

```text
compiler/v1/resolutions/{resolution_batch_id}/resolution-record.json
compiler/v1/resolutions/{resolution_batch_id}/source-snapshot.json
compiler/v1/resolutions/{resolution_batch_id}/candidate-index.json
compiler/v1/resolutions/{resolution_batch_id}/resolutions.json
compiler/v1/resolutions/{resolution_batch_id}/validation-report.json
compiler/v1/resolutions/{resolution_batch_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/resolutions/{resolution_batch_id}/result.json
compiler/v1/resolution-rejections/{resolution_attempt_id}/evidence.json
compiler/v1/resolution-rejections/{resolution_attempt_id}/result.json
```

Identical compiler evidence, Source snapshot, resolver identity, thresholds, and timestamp produce identical IDs and bytes. Existing identical objects yield `idempotent: true`; a same-key byte mismatch is an immutable collision and fails hard.

## Adjacent state sequence

```text
validated_input
→ source_indexed
→ resolved
→ review_only_complete
```

Every transition is recorded in an immutable hash-linked event. The only mutation listed by these events is `compiler_review_object_write`.

## Explicitly deferred

Provider-neutral synthesis proposals, compiler-wide proposal validation, reviewer packets, immutable human decisions, and Source PR package generation remain later M11 slices. M11.3 supplies validated resolution evidence but grants no authority to publish it.

## Production invariant

This slice leaves the production baseline unchanged:

- release: `20260708T040116Z-69a9f445699a`
- manifest SHA-256: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- pointer SHA-256: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Issue #30 remains open and receives no entry because M11.3 performs no production promotion.