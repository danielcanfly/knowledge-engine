# M24 Provenance and Source Viewer

This advances #972 while production retrieval remains lexical.

The first implementation surface is a bounded `source_viewers` payload on
`/v1/search`. Each viewer binds one public source card to the safe citations that
support visible lexical search results. The payload is release-bound and derived
only from the already ACL-filtered runtime result used by public search.

## User-Facing Contract

Each source viewer includes:

- a stable viewer ID;
- the exact release ID;
- one public source card;
- the bounded citations for that source card;
- citation, concept, and claim counts;
- snapshot and integrity availability flags;
- explicit lexical retrieval authority.

The viewer lets a product surface open a source/provenance panel from a search
result without requiring a second fetch, a semantic lookup, or access to raw
Source internals.

## Boundary

- production retrieval remains `lexical`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- source viewers expose citation locators and claim metadata, not raw evidence
  text;
- source viewers do not expose query vectors, retrieval internals, evaluation
  payloads, reviewer identities, storage keys, request headers, credentials, or
  arbitrary source snapshots;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.

## Follow-Up

Concept Wiki (#968) can reuse the same viewer contract for concept pages. Graph
navigation (#969) can open the viewer from selected nodes or edges. Obsidian
export (#971) can serialize the same bounded fields for offline review, but must
preserve the same non-serving authority boundary.
