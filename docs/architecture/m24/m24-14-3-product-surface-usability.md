# M24.14.3 Product Surface Usability

M24.14.3 turns the M24 internal Concept Wiki, lexical search, and source viewer
routes into connected product workflows. The work remains internal, read-only,
and release-pinned.

## Concept Wiki

The Concept Wiki route now exposes the loaded concept, section evidence,
relationship navigation, source handoff buttons, and a graph handoff. Because the
current committed Concept Wiki artifact is the harness page, selecting another
concept displays an explicit `concept-artifact-mismatch` state rather than
pretending a page exists.

## Lexical Search

The search route now supports deterministic client-side filtering over the
release-pinned lexical results. Results include rank, score, section identity,
citation count, concept handoff, graph handoff, and source-card handoff. A
bounded `no-match` state is shown when the query filters out all release-pinned
results.

## Source Viewer

The source route now supports source filtering, source card inspection, citation
drill-in, pinned citation state, and concept handoff from citation rows. Missing
source/citation data is represented by bounded unavailable states.

## Boundary

- production retrieval remains lexical;
- semantic promotion, semantic serving, hybrid retrieval, and production answer
  serving remain disabled;
- no Source/Foundation mutation is performed;
- no Cloudflare, DNS, Access, R2, Qdrant, production pointer, traffic, or
  credential mutation is performed;
- no runtime CDN or external network dependency is introduced.
