# M24 Source PR #19 Decision Capture

This advances #974 for `danielcanfly/knowledge-source#19`.

Source PR #19 remains a draft review surface and must not merge as-is. Daniel
authorized the recommended review decisions on 2026-07-20:

- first 11 items: `approve_new`;
- final 4 items: `edit`;
- edited items must be narrowed to harness-specific definitions in the later
  canonical adoption PR before they can be canonicalized.

## Capture Artifact

`pilot/m24/m24-source-pr-19-decision-capture.json` records:

- exact Source PR identity;
- all 15 review IDs;
- the recommended and authorized decision for each item;
- human actor and reviewed timestamp fields;
- provenance notes for the later adoption PR;
- closure requirements;
- non-serving authority boundary.

The artifact is digest-bound so a future session can detect review decision
drift before building the canonical Source adoption PR.

## Current State

- Source PR #19 is open and draft;
- Source PR #19 must not merge as-is;
- all 15 decisions are recorded in Engine review evidence;
- Source PR #19 has a matching decision comment:
  `https://github.com/danielcanfly/knowledge-source/pull/19#issuecomment-5020513924`;
- canonical Source writes remain unauthorized;
- production retrieval remains lexical.

## Closure Path

#974 may close once the Source PR #19 review surface records these same Daniel
decisions. The next implementation step is a separate canonical Source adoption
PR. That adoption PR may convert `approve_new` items directly and may convert
`edit` items only after narrowing them to harness-specific definitions.

## Boundary

- production retrieval remains `lexical`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.
