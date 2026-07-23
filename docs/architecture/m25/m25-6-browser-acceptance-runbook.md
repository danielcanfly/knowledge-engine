# M25.6 Browser Acceptance Runbook

## Candidate binding

Browser acceptance must be bound to the exact implementation PR head, the M25.6 review-batch digest,
the browser-plan digest and the retained browser-evidence artifact digest. Any head movement or
artifact drift invalidates prior acceptance.

## Required journeys

1. Approve an exact-match item.
2. Map a duplicate item to an existing concept.
3. Edit a near-match distinct item.
4. Split a parent/child candidate.
5. Reject a policy-blocked item.
6. Defer a polysemous item.

For each journey confirm that evidence locators, Source comparison, explanation signals, graph
neighbourhood, proposals and explicit diff remain visible before the decision is recorded.

## Mandatory observations

- Unauthenticated access receives `401`.
- No bulk-approval control or endpoint exists.
- The decision form requires action-specific payloads.
- Approve, map, edit and split require evidence, comparison and diff acknowledgements.
- The UI displays the immutable decision digest after submission.
- The queue reflects the recorded action.
- Audit export contains a valid hash chain.
- Six browser decisions do not make the thirty-item batch complete.
- Source write, GitHub PR creation and M25.7 remain forbidden.

## Daniel acceptance language

Acceptance must identify the exact PR and head and state whether all six protected journeys are
accepted. It must not be inferred from a general instruction to continue.

Suggested form:

> I accept the M25.6 protected browser journeys for PR #<PR> exact head `<SHA>`, including the
> approve, map, edit, split, reject and defer flows, the authenticated access boundary, item-level
> evidence and diff presentation, immutable decision ledger and audit export. This acceptance does
> not authorize M25.7.
