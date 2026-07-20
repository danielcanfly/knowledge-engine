# M24 Source PR #19 Decision Capture

This advances #974 for `danielcanfly/knowledge-source#19`.

Source PR #19 remains a draft review surface. The PR body still says every
decision is pending, and the PR has no submitted human reviews or comments. This
document therefore does not close #974 and does not claim Source approval.

## Capture Artifact

`pilot/m24/m24-source-pr-19-decision-capture.json` records:

- exact Source PR identity;
- all 15 review IDs;
- the recommended decision for each item;
- the current pending decision state;
- required human actor and reviewed timestamp fields;
- closure requirements;
- non-serving authority boundary.

The artifact is digest-bound so a future session can tell whether the review
surface changed before Daniel records final decisions.

## Current State

- Source PR #19 is open and draft;
- Source PR #19 must not merge as-is;
- all 15 decisions remain pending;
- canonical Source writes remain unauthorized;
- production retrieval remains lexical.

## Closure Path

#974 may close only after Daniel records one allowed decision for every item:

- `approve_new`;
- `map_existing`;
- `edit`;
- `reject`;
- `defer`.

Every item must also include a non-null human actor, reviewed timestamp, and
provenance note sufficient to build a later canonical Source adoption PR.

## Boundary

- production retrieval remains `lexical`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.
