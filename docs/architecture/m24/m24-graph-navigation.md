# M24 Graph Navigation

This advances #969 while production retrieval remains lexical.

The first graph navigation implementation is a renderer-neutral state model over
the existing read-only graph API payloads. It marks a selected concept, focus
neighbors, and focus edges without introducing layout coordinates, Sigma-specific
fields, semantic retrieval, or graph mutation.

## Navigation Contract

The state includes:

- release ID;
- selected concept ID;
- visible read-only nodes;
- visible read-only edges;
- focus neighbor IDs from a same-release neighborhood payload;
- available actions: select node, open concept, and open source viewer;
- truncation flags;
- explicit non-serving authority flags.

## Boundary

- production retrieval remains `lexical`;
- graph payloads must be read-only and renderer-neutral;
- focus neighborhood release identity must match the overview release identity;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- renderer mutation and Source mutation are unauthorized;
- query vectors, evaluation payloads, credentials, storage keys, raw evidence, and
  production control fields are not exposed.

## Relationship to Other M24 Lanes

Concept Wiki (#968) can open concept pages from selected nodes. Provenance/source
viewer (#972) can open source panels from concept pages or search results.
Sigma.js internal deployment (#973) can render this state with a pinned internal
client without changing the graph authority.
