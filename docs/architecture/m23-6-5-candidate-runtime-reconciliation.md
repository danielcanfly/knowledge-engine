# M23.6.5 Candidate Semantic Runtime Reconciliation

## Closure

M23.6.5 is accepted as a repository-only, deployment-ready implementation of a read-only candidate semantic Runtime and shadow endpoint. No external Runtime, Access, Workers AI, Qdrant, Source, R2, pointer or production mutation was dispatched.

- Parent issue: #383
- Submilestone issue: #399
- Implementation PR: #400
- Entry Engine main: `d0fb8b1b799d91b15520fd0bf8dacd093cf91e0d`
- Rejected implementation head: `9da2d8366b6a6b4252786130f7dfd34c71f2989c`
- Accepted implementation head: `26344362436f69c041723885aced788e5de007e3`
- Expected-head squash merge: `daafeb7d0a295e1434e1487dc2b5e0ab1e5bad24`

## Rejected-head evidence

The first implementation head was not accepted because both the general CI quality gate and the M23.6.5 workflow found five Ruff E501 line-length failures in the deterministic Python policy module.

- CI run #811: failed
- M23.6.5 Candidate Semantic Runtime run #1: failed
- M17 Architecture Canon run #142: passed
- M18 Graph v2 run #247: passed
- R2 Release Integration run #544: passed

The repair changed formatting only. It did not loosen validation, alter schemas, change query behavior, change authority flags or add any external operation.

## Accepted exact-head evidence

All workflows associated with accepted head `26344362436f69c041723885aced788e5de007e3` completed successfully:

| Workflow | Run | Run ID | Conclusion |
|---|---:|---:|---|
| M23.6.5 Candidate Semantic Runtime | #2 | `29391633413` | success |
| CI | #812 | `29391633387` | success |
| R2 Release Integration | #545 | `29391633375` | success |
| M17 Architecture Canon Acceptance | #143 | `29391633403` | success |
| M18 Graph v2 acceptance | #248 | `29391633399` | success |

The dedicated workflow accepted:

- Ruff quality gates;
- six candidate and shadow adversarial policy tests;
- byte-identical deterministic acceptance replay;
- pinned `jose`, Workers types, TypeScript and Wrangler dependency installation;
- strict TypeScript checking;
- Wrangler deployment dry-run only;
- deployment and authority guards;
- read-only Qdrant, Cloudflare Access and forbidden-mutation surface guards.

## Accepted implementation

The implementation adds:

- versioned semantic query, semantic response and shadow response schemas;
- a deterministic Python policy and simulator;
- an internal-only Cloudflare Worker package;
- fixed-issuer and fixed-audience Cloudflare Access JWT verification;
- one bounded BGE-M3 query embedding operation in the dormant runtime path;
- one read-only Qdrant Query Points operation in the dormant runtime path;
- frozen collection, named-vector, source-membership and release filters;
- fail-closed payload, score, provenance and authority validation;
- deterministic score ordering and fingerprints;
- shadow overlap and rank diagnostics that preserve lexical authority;
- strict query, top-k, body, response and timeout ceilings;
- feature flags defaulting to false;
- no public route, Workers.dev route or preview URL.

## Runtime boundary

- Worker: `llm-wiki-m23-candidate-runtime`
- Candidate route: `POST /internal/candidate/m23/retrieve`
- Shadow route: `POST /internal/candidate/m23/shadow/retrieve`
- Candidate Runtime enabled by default: false
- Shadow semantic enabled by default: false
- Public route allowed: false
- Read-only: true
- Answer generation: disabled
- Planner multi-hop: forbidden
- Production retrieval authority: lexical only

The shadow response records that lexical output remains authoritative and semantic output is not served to production. It does not merge, replace, rerank or mutate the lexical response.

## Frozen semantic identity

- Collection: `llm_wiki_m23_pilot_bge_m3_1024`
- Named vector: `default`
- Dimension: `1024`
- Distance: `Cosine`
- Embedding model: `@cf/baai/bge-m3`
- Release ID: `m23pilot-a07eb79e381ca7e635cc9139`
- Release manifest SHA-256: `a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`
- Source membership: `evaluation-only-pending-proposal`
- M23.6.3 receipt SHA-256: `0e89d9971e6fd10505b5e36113e079629c444c371d01ac6d909d717270c7c21b`

## Preserved authority boundary

The implementation and reconciliation dispatched none of the following:

- Cloudflare Worker deployment;
- Cloudflare Access application or policy creation;
- Workers AI inference;
- Qdrant read, write or delete;
- Source mutation or Source PR #19 merge;
- R2 object or pointer mutation;
- production traffic or retrieval-mode change;
- permanent-ledger mutation;
- physical deletion or credential rotation;
- public Graph Explorer deployment;
- Graph Neural Retrieval.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`. Production remains `RETRIEVAL_MODE=lexical`.

## Next legal action

M23.6.6 may build the Graph v2 plus semantic candidate release and internal Explorer, still without production authority or public deployment. Any real deployment or external candidate query requires a separate explicit authority gate.

Production mutation dispatched: false.
