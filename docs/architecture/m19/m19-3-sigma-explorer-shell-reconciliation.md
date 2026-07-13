# M19.3 Sigma.js v3 Explorer Shell Reconciliation

Status: ready to close issue #273

## Identity chain

- M19.2 reconciled Engine base: `5b9d64a9eeb1c1926ac919ccd5125cdc56933d2d`
- implementation issue: #273
- implementation PR: #274
- implementation expected head: `91a08ab877a2ad37b6cb285f6a04851d596a7d7e`
- implementation merge: `8df8ec07c8305666ad7ac6e439cbbd96782ad242`
- Source main remains `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation main remains `e5ef644053d34e89c70d2ceb37521e1c59234832`

The reconciliation branch was created from the exact implementation merge SHA.
This PR closes #273 only after its own expected-head checks pass.

## Implementation evidence

PR #274 changed exactly eight files: the M19.3 workflow and architecture note,
plus the isolated graph explorer package's ignore file, package manifest,
lockfile, TypeScript configuration, implementation, and test file. The PR had no
conversation comments, submitted reviews, or inline review threads before
merge.

All four workflows completed successfully against exact implementation head
`91a08ab877a2ad37b6cb285f6a04851d596a7d7e`:

- CI run `29233608293` (#590);
- M19.3 Sigma explorer shell run `29233608320` (#1), including the successful exact-head verification step;
- M18 Graph v2 acceptance run `29233608295` (#26);
- M17 Architecture Canon Acceptance run `29233608272` (#19).

Local verification also passed: eight graph explorer tests, nine M19.2 adapter
regression tests, zero high-severity runtime vulnerabilities in both packages,
and the full Python suite with 853 tests.

## Contract reconciled

The isolated `packages/graph-explorer` package pins Sigma.js `3.0.3`, Graphology
`0.26.0`, exact TypeScript tooling, and a committed lockfile. It accepts only an
already ACL-filtered Graphology graph marked read-only and renderer-neutral with
a non-empty release identity.

Coordinates, labels, colors, sizes, and reducer state are created only on an
ephemeral graph copy. The canonical graph is not mutated and the shell has no
fetch, authentication-broadening, publication, editing, or write-back path.
Sigma is loaded lazily from the local package only, with no CDN or runtime
network dependency.

The shell provides click and keyboard node selection, stage and Escape
deselection, camera reset, bounded deterministic textual fallback, exact release
identity, accessible container state, and idempotent teardown. Search,
neighborhood expansion, filters, provenance panels, shareable view state,
large-graph layouts, communities, and progressive loading remain reserved for
M19.4 and later.

## Protected-state reconciliation

M19.3 did not modify or promote production, the production pointer, R2 objects,
credentials, permanent ledgers, or rollback state. It did not start M19.4 and
did not add Graph Neural Retrieval. This reconciliation PR is documentation
only and dispatches no release or production action.
