# M23.6.6 Graph v2, Semantic Candidate Release, and Internal Explorer

## Decision

M23.6.6 packages the evaluation-only M23 proposal lane into one immutable, read-only candidate release. It binds the 15 pending proposal concepts, 12 reviewed typed relationships, proposal provenance, a deterministic lexical index, Graph v2, the accepted 107-point semantic/Qdrant evidence, and an internal Sigma.js Explorer descriptor.

This milestone does not deploy, publish, or promote the release. Production remains `RETRIEVAL_MODE=lexical`.

## Source-lane separation

The release records two distinct identities:

- canonical current Source main: `a6ba738d910d01d2ae99b1968f0831989934c549`;
- evaluation-only Source PR #19 head: `deb3ad1e631c2149183d10561fbceb0a1848a989`.

The PR remains draft, open, and unmerged. Candidate material is marked non-canonical, not release-eligible, and non-production-authoritative. Cross-lane merging is forbidden. A later Source adoption requires a complete derived-artifact rebuild.

## Immutable candidate release

The deterministic candidate release is:

- release ID: `m23cand-c7fbec7e945e79d05d3263b0`;
- manifest digest: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`;
- candidate source bundle: `79fb68556f35e6d5aa2eac52c683e2f78ce36c5ae941f8a7349de0a96096f768`;
- lexical index: `d9185dba04e27c25ab8c3d30f7d4894bcf1700b2e4234e06285f06345cc6d50d`;
- provenance: `93161e88102f1518630bd92370dddf46d1b81cc149ed82800c88db19f30e2c9d`;
- Graph v2: `9e87b4ee48ad6900d5b32d493ddaa3e2d05eca1dbfb4d52b87f4bc3ef15af380`;
- semantic point index: `36df2156d37323e40b9bf172fe308f3513c5249e3a10553970f5606c20770e86`;
- semantic anchor map: `031f168698c5fad1acff2e7d277d101c2ab36e9acb2b9354a667ca5f11b70efc`.

All hashes above are file digests over canonical JSON plus one trailing newline. The manifest's own `manifest_sha256` is calculated over canonical JSON with the self-digest field omitted.

## Graph and semantic identity model

The proposal Graph v2 contains exactly 15 candidate nodes and 12 typed edges. It remains renderer-neutral and carries no coordinates, colours, sizes, hidden flags, camera state, or layout data.

The accepted Qdrant points map to three source-document anchors:

- `pilot/harness-theory-part-01`: 29 sections;
- `pilot/harness-theory-part-02`: 40 sections;
- `pilot/harness-theory-part-03`: 38 sections.

Each proposal concept maps to one evidence-derived source anchor. The available evidence does not support assigning those shared anchor sections to individual proposal concepts. The release therefore records anchor-level coverage only and explicitly sets `per_concept_section_attribution_available=false`.

Typed relationships and semantic neighbours are separate layers:

- typed edges are governed proposal relationships;
- semantic neighbours are renderer-only overlays supplied to the Explorer;
- semantic edges are not materialised into Graph v2;
- semantic overlays never mutate the Graphology graph.

## Existing graph stack reuse

The candidate Graph API payload uses `knowledge-engine-graph-api/v1`, allowing the existing M19 Graphology adapter to validate and import it without a parallel graph implementation.

The existing `@knowledge-os/graph-explorer` package remains responsible for:

- Sigma.js 3.0.3 rendering;
- deterministic search, focus, filters, and neighbourhood controls;
- detail and provenance models;
- deterministic scale, overview, semantic zoom, and progressive paging;
- Phase B CSP, accessibility, read-only, and release-separation acceptance.

M23.6.6 adds only the candidate-release overlay model and renderer-only semantic neighbourhood descriptors.

## Internal Explorer boundary

The Explorer remains:

- feature-gated by `GRAPH_EXPLORER_ENABLED=false`;
- internal-only;
- read-only;
- protected by a later Cloudflare Access deployment gate;
- free of runtime browser network clients;
- free of browser persistence and write-back;
- free of edit controls;
- free of Graph Neural Retrieval.

No public route or deployment configuration is added by this milestone.

## Offline acceptance

The exact-head workflow performs:

1. Python lint and eight adversarial candidate-release tests;
2. two deterministic acceptance replays with byte-for-byte comparison;
3. candidate manifest, artifact, graph, semantic-point, anchor, Graph API, and Explorer cross-checks;
4. Graphology adapter regressions;
5. the complete Graph Explorer suite, including candidate overlay tests;
6. 1k/10k/50k performance fixtures;
7. Phase B CSP/network/persistence/write-back scanning;
8. runtime npm audits and TypeScript builds;
9. static no-deployment/no-mutation authority scans.

## Authority boundary

This implementation dispatches no R2 write, Worker or Pages deployment, Access application creation, Workers AI inference, Qdrant read/write/delete, Source mutation, Source PR #19 merge, production pointer or traffic change, permanent-ledger mutation, deletion, credential rotation, public Explorer, or Graph Neural Retrieval.
