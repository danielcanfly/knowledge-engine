# M24 Concept Wiki

This advances #968 while production retrieval remains lexical.

The first Concept Wiki implementation is a typed page view model. It composes a
public lexical search response with an optional read-only graph neighborhood to
produce a concept page: sections, relationship rows, source viewers, provenance
metadata, and explicit authority flags.

## Page Scope

Concept pages include:

- concept ID, title, and optional graph description;
- visible sections from public lexical search results;
- section excerpts and score/rank metadata;
- source viewer IDs and source card IDs for each section;
- bounded source viewers with citation locator and claim metadata;
- read-only relationship rows from graph neighborhood data.

## Relationship Display Rules

Relationships are display-only. Each row contains a stable edge ID, relation
type, direction, neighboring concept ID, neighboring title, confidence, and
generated-inverse marker. The page accepts only same-release graph neighborhood
data and limits relationship rows to twenty.

## Boundary

- production retrieval remains `lexical`;
- graph data is read-only and already ACL-filtered before page composition;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- raw evidence text, query vectors, retrieval internals, evaluation payloads,
  reviewer identities, storage keys, credentials, and arbitrary source snapshots
  are not exposed;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.

## Follow-Up

Graph navigation (#969) can use the same relationship rows for selected-neighbor
movement. Sigma.js internal deployment (#973) can consume the read-only graph
payloads separately without changing this non-serving Concept Wiki authority.
