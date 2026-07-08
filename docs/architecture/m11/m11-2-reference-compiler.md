# M11.2 Deterministic Local Markdown Reference Compiler

Status: implementation candidate
Parent milestone: #146
Slice issue: #149
Baseline: `b4a1f6c4b7b59b1127ae9600a4f48625c8a111c6`

## Purpose

M11.2 proves the executable handoff from M10 immutable intake evidence to M11 review-only compiler artifacts. It accepts only an admitted M10 local Markdown snapshot and normalized derivative. It performs no network acquisition, model invocation, Source lookup, synthesis, GitHub governance action, release operation, production mutation, or permanent-ledger append.

## Modules

- `compiler_contract_v1.py` verifies exact M10 object keys, hashes, identities, admission events, connector and normalizer versions, audience, ACL, owner, and license. It also defines deterministic run identity, immutable writes, typed failures, and replay results.
- `compiler_markdown_v1.py` deterministically structures front matter, headings, paragraphs, lists, list items, quotations, and fenced code. It emits exact normalized-character and line source maps, plus bounded concept, claim, definition, date, and citation candidates.
- `compiler_v1.py` orchestrates the adjacent state sequence `admitted -> structured -> extracted -> review_only_complete`, writes only immutable `compiler/v1/` artifacts, and produces typed sanitized rejection evidence.

## Input boundary

The compiler receives object references and SHA-256 values, not an arbitrary local source path. The accepted connector is exactly `local_file` version `local-file/1.0.0`; the accepted normalizer is exactly `markdown` version `1.0.0` with `text/markdown` output. The M10 result and its hash-linked event chain must end in `accepted_for_compilation`.

## Output layout

```text
compiler/v1/runs/{compiler_run_id}/input.json
compiler/v1/runs/{compiler_run_id}/structured/blocks.json
compiler/v1/runs/{compiler_run_id}/structured/source-map.json
compiler/v1/runs/{compiler_run_id}/extraction/candidates.json
compiler/v1/runs/{compiler_run_id}/events/{ordinal}-{event_sha256}.json
compiler/v1/runs/{compiler_run_id}/result.json
compiler/v1/rejections/{compiler_run_id}.json
```

All persistent writes are immutable. Exact replay returns the same IDs and bytes with `idempotent: true`. A collision with different bytes is a hard integrity failure.

## Evidence continuity

Every extraction candidate references a structured block and source-map object. Every source-map segment records normalized character offsets, line ranges, the exact quote, and its SHA-256. Prompt-like text remains untrusted source data and cannot alter compiler configuration.

## Explicitly deferred

M11.2 does not perform canonical Source resolution, duplicate or contradiction classification, supersession, provider-backed extraction, synthesis proposals, validation packets, human decisions, or Source PR packaging. Those remain later M11 slices and must use the merged M11.1 contracts.

## Acceptance

The slice must pass repository lint, the complete test suite, reference vertical slice, and container build. Inspection must confirm that all new persistent namespaces are under `compiler/v1/`, no arbitrary source path enters the compiler request, no forbidden execution or publication imports are introduced, and the production baseline remains unchanged.