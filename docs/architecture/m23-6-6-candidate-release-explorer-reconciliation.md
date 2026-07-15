# M23.6.6 Graph v2 Semantic Candidate Release and Internal Explorer Reconciliation

## Closure

M23.6.6 is accepted as a repository-only, deterministic and deployment-ready implementation of an immutable candidate release plus internal read-only Explorer overlay. No external candidate release publication, Runtime deployment, R2 write, Qdrant operation, Source change or production mutation was dispatched.

- Parent issue: #383
- Submilestone issue: #402
- Implementation PR: #403
- Entry Engine main: `0eecc89bb711e7df8976a79d46bcd2d1072be44a`
- Accepted implementation head: `2a5a9ea181d0ed35f9e46b89139e2d2103b96804`
- Expected-head squash merge: `22cc6c51dac5c21251ed6350b40c94e452143e10`

## Accepted exact-head workflows

All pull-request workflows associated with the accepted implementation head completed successfully:

| Workflow | Run | Run ID | Conclusion |
|---|---:|---:|---|
| M23.6.6 Candidate Release and Internal Explorer | #1 | `29392785481` | success |
| CI | #816 | `29392785495` | success |
| R2 Release Integration | #547 | `29392785435` | success |
| M17 Architecture Canon Acceptance | #145 | `29392785470` | success |
| M18 Graph v2 acceptance | #252 | `29392785456` | success |
| M19.3 Sigma explorer shell | #13 | `29392785472` | success |
| M19.4 graph explorer interactions | #11 | `29392785457` | success |
| M19.5 detail provenance panels | #9 | `29392785443` | success |
| M19.6 large graph strategy | #7 | `29392785449` | success |
| M19.7 Phase B acceptance | #5 | `29392785460` | success |

The dedicated exact-head workflow accepted:

- Ruff and eight adversarial candidate-release tests;
- byte-identical dual deterministic release generation;
- artifact bundle decompression and all fixed hash checks;
- candidate release self-digest verification;
- 15 candidate concepts and 12 governed typed relationships;
- 107 Qdrant sections across exact evidence-anchor counts 29, 40 and 38;
- refusal to invent per-concept section attribution;
- strict separation of governed typed edges and renderer-only semantic neighbours;
- Graphology adapter and the complete Sigma Explorer regression suite;
- 1k, 10k and 50k scale fixtures;
- CSP, accessibility, network, persistence and write-back scans;
- runtime npm audits, TypeScript builds and repository quality gates;
- deployment, authority and forbidden-mutation guards.

## Frozen candidate identity

- Candidate release ID: `m23cand-c7fbec7e945e79d05d3263b0`
- Candidate manifest identity: `3303a1d54d448c96c724178b482dc73daed2712ba8d09b0e34fa96eb8761e560`
- Candidate source bundle SHA-256: `79fb68556f35e6d5aa2eac52c683e2f78ce36c5ae941f8a7349de0a96096f768`
- Candidate lexical index SHA-256: `d9185dba04e27c25ab8c3d30f7d4894bcf1700b2e4234e06285f06345cc6d50d`
- Candidate provenance SHA-256: `93161e88102f1518630bd92370dddf46d1b81cc149ed82800c88db19f30e2c9d`
- Candidate Graph v2 SHA-256: `9e87b4ee48ad6900d5b32d493ddaa3e2d05eca1dbfb4d52b87f4bc3ef15af380`
- Semantic reference SHA-256: `36df2156d37323e40b9bf172fe308f3513c5249e3a10553970f5606c20770e86`
- Semantic anchor map SHA-256: `031f168698c5fad1acff2e7d277d101c2ab36e9acb2b9354a667ca5f11b70efc`
- Graph API payload SHA-256: `ddd34961ea7415ec7bcc3ed71ec84ff5564136a6715ba0f9038c389beb2132fc`
- Explorer overlay SHA-256: `8a2d60c6c3764d896ebd9c2d509ea8206c86f4028c82b4c9e6cdf7223f0944f1`

The `manifest_sha256` above is the self-digest over canonical manifest JSON with the self-digest field omitted. The committed artifact hash for the complete manifest file is `dae9bf3086551ef8bb4ab957598f0a04414a8685e89ba2306e0f61c862b3f745`.

## Graph and semantic boundary

The candidate Graph v2 contains 15 pending-human-review nodes and 12 reviewed typed relationships. It remains renderer-neutral and candidate-only.

The 107 semantic points remain bound to three evidence anchors:

- `pilot/harness-theory-part-01`: 29;
- `pilot/harness-theory-part-02`: 40;
- `pilot/harness-theory-part-03`: 38.

These anchor counts are shared evidence coverage. They are not attributed to individual proposal nodes. Semantic neighbours are renderer-only descriptors and are never materialised into typed Graph v2 edges.

## Internal Explorer boundary

The implementation reuses the accepted M19 Graphology and Sigma.js stack and adds only a candidate-release overlay module. The Explorer remains:

- `GRAPH_EXPLORER_ENABLED=false` by default;
- internal-only and read-only;
- free of public routes;
- free of runtime browser network clients;
- free of browser persistence, editing and write-back;
- free of Graph Neural Retrieval.

## Preserved authority boundary

The implementation and reconciliation dispatched none of the following:

- R2 candidate object or pointer mutation;
- Worker, Pages or Graph Explorer deployment;
- Cloudflare Access application or policy creation;
- Workers AI inference;
- Qdrant read, write or delete;
- Source mutation or Source PR #19 merge;
- production traffic or retrieval-mode change;
- permanent-ledger mutation;
- physical deletion or credential rotation;
- public Graph Explorer;
- Graph Neural Retrieval.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`. Production remains `RETRIEVAL_MODE=lexical`.

## Next legal action

M23.6.7 may perform full M23.6 acceptance, closure and reconciliation. Any real candidate R2 publication, Worker/Pages deployment, Access setup, Qdrant query or public exposure requires a separate explicit authority gate.

Production mutation dispatched: false.
