# M23.6.1 Pilot Authority and Candidate Identity Contract

## Decision

M23.6.1 establishes a deterministic non-production envelope before any Qdrant manifest,
external upsert, Worker/Queue deployment, candidate Runtime or Graph Explorer release.
It grants no external-write or production authority.

`RETRIEVAL_MODE=lexical` remains the only production-authoritative retrieval mode.

## Exact baseline

- Engine: `e6557ff8b3f6eb8ce7cd206df5bf0a4794ae34fb`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.5 evidence ZIP SHA-256: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`
- semantic artifact: `semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d`
- Qdrant collection: `llm_wiki_m23_pilot_bge_m3_1024`
- named vector: `default`, dimension `1024`, distance `Cosine`

## Read-only production snapshot

The latest accepted production identity remains:

- release: `20260708T040116Z-69a9f445699a`
- manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

The snapshot is grounded in accepted M17.7 PR #248 and the successful, non-mutating
R2 Release Integration run `29352865671` executed against the M23.5 accepted head.
The workflow did not print or mutate the production pointer. Therefore M23.7.8 must perform
a fresh read-only production inspection before any final promotion decision. This contract
must never be interpreted as permission to update the pointer.

## Source PR #19 adoption lane

The selected lane is **evaluation-only pending proposal**.

Source PR #19 remains draft, open and unmerged at head
`deb3ad1e631c2149183d10561fbceb0a1848a989`. No explicit adoption approval exists.
Consequently:

- current Source main is the only canonical Source identity;
- all 107 frozen Harness sections may be indexed only in an evaluation-only pilot lane;
- those points must keep `canonical_knowledge=false`,
  `candidate_release_eligible=false` and `production_authority=false`;
- the later candidate release must rebuild semantic artifacts from exact current Source;
- any later approved Source adoption invalidates Source, lexical, provenance, Graph v2,
  semantic and Qdrant-manifest identities and requires a complete deterministic rebuild.

There is no implicit adoption path.

## Candidate identity

A candidate release identity is complete only when it binds exact digests for:

1. Engine, Source and Foundation commits;
2. Source bundle;
3. lexical index;
4. provenance;
5. Graph v2;
6. semantic manifest and semantic vectors;
7. embedding provider/model/dimension;
8. Qdrant collection and ingestion manifest;
9. authority profile and Source-adoption lane.

The release identifier is `m23cand-` plus the first 24 hexadecimal characters of SHA-256
over canonical JSON of the complete identity tuple, excluding the identifier itself.
Missing digests, moving refs and cross-release composition are rejected.

## Qdrant contract

The collection is fixed to `llm_wiki_m23_pilot_bge_m3_1024`. The unrelated
`llamaindex_demo_hybrid` collection is explicitly blocked. Points use named vector
`default`, dimension 1024 and Cosine distance.

Payload is limited to stable retrieval, ACL, release and provenance fields declared by
`pilot/m23/m23-6-1-authority-contract.json`. Credentials, mutable operator notes,
raw exceptions and production authority are forbidden.

The write default is deny. The first write remains unauthorised, requires a separately
reviewed M23.6.2 manifest, explicit operator approval immediately before M23.6.3, and a
read-only proof that the collection is green and empty. Delete authority is absent.

## Candidate R2 retention

Candidate objects, if separately authorised later, live only beneath:

```text
candidates/m23/{candidate_release_id}/
```

They remain immutable through M23.7 and enter cleanup review 30 days after M23.7 closes.
There is no automatic deletion. Physical deletion requires a separate governed operation.
Production release and pointer namespaces are forbidden.

## Worker and Queue envelope

Reserved non-production names:

- Worker: `llm-wiki-m23-pilot-embed-consumer`
- Queue: `llm-wiki-m23-pilot-embed`
- DLQ: `llm-wiki-m23-pilot-embed-dlq`

The future implementation is capped at three total delivery attempts, four messages per
batch, 25 sections per message, concurrency two, 500 sections per run and 2,000 sections
per day. An operator-supplied price estimate is required, with hard ceilings of USD 0.50
per run and USD 2.00 per day. Deployment is not authorised by M23.6.1.

## Candidate Runtime and Explorer

The candidate Runtime is read-only beneath `/internal/candidate/m23`, authenticated by a
Cloudflare Access JWT with a fixed audience. It exposes no public fallback and permits at
most bounded single-hop graph neighbourhood retrieval. Planner-driven multi-hop remains off.

The Explorer reuses `packages/graph-explorer` and Sigma.js 3.0.3. Its intended deployment
is a Cloudflare Pages internal preview protected by the same fixed-audience Access boundary.
It is read-only, has no editing surface, has no public route and remains disabled by
`GRAPH_EXPLORER_ENABLED=false`.

## Reserved answer-provider ceilings

Answer composition remains disabled until M23.7.4 and no provider is selected here. The
future candidate-only evaluation lane is capped at two attempts, 4,000 input tokens,
800 output tokens, USD 0.05 per query and USD 5.00 per day. It has no production-answer
authority.

## Acceptance and next legal action

Run:

```bash
python scripts/m23_6_1_authority_acceptance.py \
  --contract pilot/m23/m23-6-1-authority-contract.json \
  --output .artifacts/m23/m23-6-1-authority-acceptance.json
```

M23.6.1 may proceed to reconciliation only when dedicated exact-head CI and all triggered
regressions are green. The next legal engineering action is M23.6.2, which builds the
deterministic 107-point ingestion manifest without network or write authority.

Production mutation dispatched: false.

## Contract reconciliation

Implementation PR #385 was accepted from exact head
`2a284811d36128ec44a16c694930e620b7ee485d` and merged as
`620d0dba184d5bbda7e32a86fb7fb388017778fc`.

The accepted exact-head checks were all green:

- M23.6.1 Pilot Authority Contract run `29382687615` (run 2);
- CI run `29382687591` (run 777);
- R2 Release Integration run `29382687626` (run 520);
- M17 Architecture Canon Acceptance run `29382687589` (run 125);
- M18 Graph v2 acceptance run `29382687598` (run 213).

The accepted implementation performed no Cloudflare embedding call, Qdrant write, R2
mutation, production pointer mutation, Source mutation, Source PR #19 merge, production
traffic change, public deployment, permanent-ledger mutation, physical deletion or
credential rotation. Source PR #19 remains draft, open and unmerged. Production retrieval
remains lexical, Graph Explorer remains disabled and Graph Neural Retrieval remains
forbidden.

M23.6.1 is reconciled. The next legal action is M23.6.2 deterministic ingestion-manifest
construction with no network and no write authority.
