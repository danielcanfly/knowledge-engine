# M24.14.2 Sigma Graph Explorer

M24.14.2 integrates the M24 internal product shell with a real Sigma.js browser
renderer. The graph route now loads local Graphology and Sigma assets, builds a
read-only graph from `site/data/graph-navigation.json`, and renders an
interactive canvas in the authenticated internal app.

The implementation remains a product UI lane only:

- production retrieval remains lexical;
- semantic promotion, semantic serving, hybrid retrieval, and production answer
  serving remain disabled;
- no Cloudflare, DNS, Access, R2, Qdrant, production pointer, traffic, or
  credential mutation is performed;
- no runtime CDN dependency is introduced.

## Runtime Contract

The browser loads these same-origin assets in order:

1. `vendor/graphology.umd.min.js`
2. `vendor/sigma.min.js`
3. `graph-explorer.js`
4. `app.js`

`graph-explorer.js` consumes the release-pinned graph-navigation artifact,
normalizes it into a Graphology mixed graph, and gives that graph to Sigma for
canvas rendering. The app shell continues to validate release identity before
any route renders.

## Interaction Contract

The graph route supports:

- pan and zoom through Sigma camera controls;
- camera reset;
- node search across title, aliases, tags, description, and node id;
- node selection by canvas click or search result;
- one-hop and two-hop neighbor focus;
- relation type filtering;
- show-orphans toggle;
- bounded empty-filter and runtime-unavailable states;
- selection details with source path, tags, type, and neighbor count.

The textual fallback remains available through the route structure and bounded
state panels, but the primary graph surface is now a Sigma.js canvas.
