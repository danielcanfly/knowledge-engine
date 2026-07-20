# M24 Lexical Search UX

This advances #970 while production retrieval remains lexical.

The first implementation surface is `/v1/search`, a public lexical search API
that turns the existing governed runtime query result into scan-friendly result
cards. It does not add semantic retrieval, semantic answer serving, hybrid
retrieval, or production promotion.

## User-Facing Contract

Search responses include:

- ranked result cards with concept ID, section ID, title, section title, excerpt,
  score, citation ordinals, source card IDs, and source kinds;
- source cards reused from the public citation contract;
- stable concept IDs;
- release-bound request IDs;
- explicit empty state with `status=not_found`;
- sort metadata and filter metadata.

Supported sort modes:

- `relevance`: keep lexical runtime order;
- `title`: sort by title, section title, then section ID.

Supported filter:

- `source_kind`: keep only results backed by at least one source card of that
  kind.

## Boundary

- `Runtime.query()` remains the only retrieval path used by `/v1/search`;
- production retrieval remains `lexical`;
- public search does not expose retrieval internals or evaluation payloads;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.

## Follow-Up

Later #970 work may add frontend controls for sort and source-kind filtering.
Concept Wiki (#968), graph navigation (#969), and provenance/source viewer (#972)
can consume the same search response without changing retrieval authority.
