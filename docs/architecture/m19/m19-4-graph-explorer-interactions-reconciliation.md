# M19.4 Graph Explorer Interactions Reconciliation

Status: ready to close issue #276

## Identity chain

- M19.3 reconciled Engine base: `9327bef8b1ad14cfbe9b7047ad97c8b26322a35b`
- implementation issue: #276
- implementation PR: #277
- implementation expected head: `9f561e545bcaf19f64b4d366c71e35405dc58481`
- implementation merge: `d93705ef049d16d9fd7e92a765c52db4cd80eb5e`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

The reconciliation branch was created from the exact implementation merge SHA.
This PR closes #276 only after its own expected-head checks pass.

## Implementation evidence

PR #277 changed exactly four files: the M19.4 exact-head workflow, architecture
contract, explorer implementation, and explorer tests. The PR had no conversation
comments, submitted reviews, or inline review threads before merge.

All five workflows completed successfully against exact implementation head
`9f561e545bcaf19f64b4d366c71e35405dc58481`:

- CI run `29236105018` (#594);
- M17 Architecture Canon Acceptance run `29236105016` (#21);
- M18 Graph v2 acceptance run `29236105014` (#30);
- M19.3 Sigma explorer shell run `29236105025` (#5);
- M19.4 graph explorer interactions run `29236105034` (#1).

The M19.4 workflow verified the exact checked-out head, the nine-test M19.2
Graphology adapter regression suite, the fifteen-test graph explorer suite, and
both production-runtime npm audits with zero high-severity vulnerabilities. The
repository CI quality gates, reference vertical slice, and container build also
passed.

## Contract reconciled

The explorer now provides NFKC-normalized and bounded concept search across
stable ID, title, aliases, bounded description, tags, and type. Results are
ranked deterministically and capped at 100 from the current visible ACL-safe
view.

Focus traversal is local, direction-neutral for viewing, and bounded to one or
two hops. Relation filters apply before traversal. Tag and concept-type filters
use OR semantics within a family and AND semantics across families. Filter
values are normalized, deduplicated, sorted, and capped at 50. Orphan visibility
is explicit, while an isolated focus node remains visible.

Search matches, hidden state, labels, sizes, highlighting, and z-index remain
Sigma reducer output over an ephemeral projection. The canonical graph is not
mutated. Selection is cleared when it leaves the visible graph, and keyboard and
text fallback ordering follows the deterministic visible-node set.

## Protected-state reconciliation

M19.4 did not modify or promote production, candidate state, the production
pointer, R2 objects, credentials, permanent ledgers, or rollback state. It did
not add provenance panels, shareable state, large-graph layout, M19.5 work, or
Graph Neural Retrieval. This reconciliation PR is documentation only and
dispatches no release or production action.
