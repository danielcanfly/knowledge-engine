# M18.6 Runtime Graph Compatibility

Status: implementation

Issue: #261

Production mutation dispatched: false

## Compatibility contract

Runtime continues to require the legacy `lexical_index`, `graph`, and
`provenance` artifacts. The `graph_v2` artifact is loaded, validated, and retained
when present, but it is optional during the compatibility window so an immutable
pre-M18 release remains loadable.

The generic `graph.json` neighbor expansion remains the default graph behavior.
The lexical seed calculation, deterministic ordering, result bound, citations,
and raw-Source fallback prohibition are unchanged.

## Gated relation hook

`RELATION_AWARE_EXPANSION_ENABLED` is a strict boolean and defaults to `false`.
When disabled, graph v2 cannot add candidates or alter scores. Runtime still
reports internally whether graph v2 was available and validated.

When explicitly enabled, the hook:

- starts only from the existing lexical/semantic seed set;
- traverses at most one typed edge;
- considers at most twenty deterministic typed neighbors per seed;
- rechecks both node and edge audiences before adding a candidate;
- keeps generic-neighbor expansion active;
- attaches edge identity, relation type, direction, confidence, review, and
  provenance references to the internal Runtime result;
- does not expose internal retrieval evidence through the bounded public ask
  response contract.

Directed traversal follows compiled edge direction. The compiler already emits
approved inverse edges where the ontology defines them. Undirected edges are
available from either endpoint without creating a second canonical edge.

## Activation integrity

Before replacing the last-known-good active release, Runtime rejects graph v2
when schema or release identity differs, renderer fields leak, node or edge
identity is invalid, an endpoint is missing, an audience is broadened, direction
or inverse markers are malformed, a relation is unapproved, or confidence is out
of bounds.

Graph v2 is an internal compatibility and retrieval artifact in M18.6. This work
does not create a Graph API, renderer adapter, Explorer, hybrid ranker, multi-hop
planner, or Graph Neural Retrieval.

## Mutation boundary

All M18.6-specific acceptance uses repository tests and filesystem-backed
fixtures. No M18.6 code path or operator action authorizes candidate publication,
production promotion, production pointer change, persistent R2 mutation,
credential change, permanent ledger append, lifecycle mutation, or rollback
mutation. Existing repository-wide PR checks may exercise a run-isolated R2 test
channel with mandatory cleanup; that CI boundary is reconciled separately from
feature activation.
