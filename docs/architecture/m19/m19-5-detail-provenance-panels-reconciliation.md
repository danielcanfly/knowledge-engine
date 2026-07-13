# M19.5 Detail and Provenance Panels Reconciliation

Status: ready to close issue #279

## Identity chain

- M19.4 reconciled Engine base: `b8f42052adfbc12b82c09ce49003b1915a663104`
- implementation issue: #279
- implementation PR: #280
- implementation expected head: `275e116bfcc78e739536c20b8f9452896d3e535f`
- implementation merge: `ed61f10673dbefa8a1c6a9899a6621293859584b`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

The reconciliation branch was created from the exact implementation merge SHA.
This PR closes #279 only after its own expected-head checks pass.

## Implementation evidence

PR #280 changed exactly five files: the M19.5 exact-head workflow, architecture
contract, graph-explorer package export, isolated details controller, and details
tests. It did not modify the M19.4 interaction implementation or the dependency
lockfile. The PR had no conversation comments, submitted reviews, or inline
review threads before merge.

All six workflows completed successfully against exact implementation head
`275e116bfcc78e739536c20b8f9452896d3e535f`:

- CI run `29237711621` (#598);
- M17 Architecture Canon Acceptance run `29237711733` (#23);
- M18 Graph v2 acceptance run `29237711641` (#34);
- M19.3 Sigma explorer shell run `29237711643` (#7);
- M19.4 graph explorer interactions run `29237711588` (#5);
- M19.5 detail provenance panels run `29237711684` (#1).

The M19.5 workflow verified the exact checked-out head, the nine-test M19.2
Graphology adapter regression suite, the complete twenty-two-test graph explorer
package including seven M19.5 detail tests, and both production-runtime npm
audits with zero high-severity vulnerabilities. Repository quality gates,
reference vertical slice, and container build also passed.

## Contract reconciled

The additive `@knowledge-os/graph-explorer/details` controller exposes exact
release, manifest, Source, Foundation, and content identities already carried by
the ACL-safe Graphology graph. Optional detail metadata must match that complete
identity exactly and remain read-only.

Node panels expose bounded canonical details, a validated relative Markdown
link, and approved provenance references. Edge panels expose stable edge and
endpoint identities, relation semantics, direction, audience, confidence,
generated-inverse status, and approved provenance references. M19.4 visible node
and edge sets can clear detail state when filters or focus hide a selected
object.

Cross-release bundles, unknown nodes or edges, duplicate records or references,
unsafe or traversing paths, arbitrary URL schemes, invalid anchors, unapproved
references, and more than twenty references fail closed. Selection styling is
renderer-only. The canonical graph remains unchanged, and no raw evidence or
reviewer identity is disclosed.

## Protected-state reconciliation

M19.5 did not modify or promote production, candidate state, the production
pointer, R2 objects, credentials, permanent ledgers, or rollback state. It added
no network client, persistence, authorization broadening, shareable state,
layout, M19.6 work, or Graph Neural Retrieval. This reconciliation PR is
documentation only and dispatches no release or production action.
