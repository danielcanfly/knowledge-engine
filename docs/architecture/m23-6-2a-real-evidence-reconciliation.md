# M23.6.2a real-evidence reconciliation

## Status

M23.6.2a is complete. The deterministic Qdrant ingestion planner now accepts and
validates the exact frozen M23.5 evidence layout without weakening the M23.6.1
authority boundary.

Parent milestone: #383  
Repair issue: #390  
Implementation PR: #391

Accepted implementation head:
`78cc20e1c076ce388a80553b0162f178a27d90bb`

Implementation merge commit:
`067e5d70c8204d0976a917ef0ff2b2b9a0e8d932`

## Real evidence identity

Evidence archive:
`M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip`

Evidence ZIP SHA-256:
`1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`

The archive contains one root, ten files and a receipt that covers every non-receipt
file. All receipt byte counts and SHA-256 values were revalidated before planning.

Semantic artifact:
`semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d`

Authority contract SHA-256:
`c28a5d3503b24358c240283cfa1b4629c3e0bfeb6c854f72725481ff4c4a1941`

## Contract repair

The real evidence exposed three assumptions that had been encoded by the synthetic
M23.6.2 fixture but were not promised by the frozen evidence contract:

1. `pilot-document-vectors.f32` and
   `semantic-artifact/semantic-vectors.f32` are independent valid BGE-M3 provider
   generations. Both contain 107 normalized 1024-dimensional float32 vectors, but
   they are not byte-identical.
2. Semantic metadata records the accepted M20 evaluation-suite digest from the
   lexical, vector and `rrf_hybrid_k60` results in `benchmark-results.json`; it does
   not record the canonical JSON digest of `benchmark-suite.json`.
3. Semantic row numbers are local to the semantic artifact. The semantic artifact
   contains the same complete 107-section identity set but in a different order, so
   cross-artifact validation must join by `section_id` rather than physical row.

The repaired planner therefore:

- keeps `pilot-document-vectors.f32` as the Qdrant ingestion source so the planned
  collection reproduces the accepted M23.5 benchmark;
- validates the semantic vectors independently for byte length, finite values,
  normalization and metadata digest;
- binds the semantic suite digest to all three accepted M20 method results;
- enforces 107 unique semantic rows and an exact 107-section set joined by
  `section_id`;
- retains deterministic UUIDv5 point IDs and the exact 20-field payload contract;
- retains immutable output and all no-network/no-write guards.

Pilot document-vector SHA-256:
`657106234f1101759449a4b42a0b7b524ea201d3355f6e89621ac8a2f532eee6`

Semantic vector SHA-256:
`d44ad902635a30691f0b83814c7598f3710dc092938ca0d49aecac5982f74ddf`

Accepted M20 suite SHA-256:
`6a15cfd45f38ef1df36a9aab6d95eb1877d669b729a9e3a5380a8c19c0c7cb36`

Canonical benchmark-suite JSON SHA-256:
`086cfb2648626dbe2cca64376dffaa6aea24e807c71f6b2b89e9ab1796d67f0e`

## Real 107-point dry run

The corrected planner generated and independently revalidated the real immutable
M23.6.2 dry-run bundle.

Manifest SHA-256:
`2814f138f2314779d77738f1e9bd3d0d0d7d388769244c3367232e5b278a0868`

Pilot release ID:
`m23pilot-a07eb79e381ca7e635cc9139`

Pilot release-manifest SHA-256:
`a07eb79e381ca7e635cc91397c322fd6ff57a62b5571a54866d26aefb734ebe9`

Output files:

| File | Bytes | SHA-256 |
|---|---:|---|
| `ingestion-manifest.json` | 57,323 | `5f6fec1e4d54715d0718376b6d2da2761ca6d927ea65765ddfecacf43d55b983` |
| `qdrant-points.json` | 2,441,122 | `0f1178949a5eccd7dec6c41ad09da423d65ff88de3a2d91c4a01319bd964963b` |
| `dry-run-receipt.json` | 706 | `0fe251c6caacc51b76e8d6bfd6a67b4b5e3112bfa9547228975aafb51e15250a` |

Bundle ZIP SHA-256:
`ca803a365fdf6b3cd8f10bc1b75f188e433000d671251281cb36ef47e316378b`

Validation results:

- point count: 107;
- unique deterministic point IDs: 107;
- collection: `llm_wiki_m23_pilot_bge_m3_1024`;
- blocked collection: `llamaindex_demo_hybrid`;
- vector name: `default`;
- vector dimension: 1024;
- distance: Cosine;
- every payload has `canonical_knowledge=false`;
- every payload has `candidate_release_eligible=false`;
- every payload has `production_authority=false`;
- output self-digests, byte counts and file SHA-256 values match;
- network calls: 0;
- Qdrant reads: 0;
- Qdrant writes: 0.

## Exact-head acceptance

The accepted head `78cc20e1c076ce388a80553b0162f178a27d90bb` passed every triggered
workflow:

| Workflow | Run | Run ID |
|---|---:|---:|
| CI | 790 | 29388319797 |
| R2 Release Integration | 529 | 29388319742 |
| R2 Canary | 246 | 29388319811 |
| M16 Security Contract Acceptance | 36 | 29388319759 |
| M16 ACL and Injection Security Acceptance | 35 | 29388319770 |
| M16 Promotion Containment Acceptance | 33 | 29388319747 |
| M16 R2 Object Restoration Acceptance | 31 | 29388319800 |
| M16 Source and Control-Plane Reconstruction Acceptance | 29 | 29388319822 |
| M16 Replay and Recovery Objectives Acceptance | 26 | 29388319785 |
| M16 End-to-End Restore Drill Acceptance | 24 | 29388319772 |
| M17 Operator Tooling Acceptance | 22 | 29388319793 |
| M17 Operator Qualification Acceptance | 17 | 29388319803 |
| M17 GA Evidence Matrix Acceptance | 16 | 29388319788 |
| M17 Independent Operator GA Acceptance | 15 | 29388319757 |
| M18 Graph v2 acceptance | 226 | 29388319741 |
| M23.2 Live Intake | 15 | 29388319820 |
| M23.3 Real AI Extraction | 14 | 29388319743 |
| M23.4 Human Review Source PR | 12 | 29388319764 |
| M23.5 Cloudflare Qdrant contract | 11 | 29388319821 |
| M23.5 corrected benchmark contract | 7 | 29388319740 |
| M23.6.2 Qdrant Ingestion Manifest | 8 | 29388319749 |

PR #391 had no comments, reviews or review threads. It was merged with the expected
head SHA after all exact-head workflows succeeded.

## Authority boundary

This repair and real dry run performed no Cloudflare call, Qdrant read or write, R2
mutation, pointer mutation, Source mutation, Source PR #19 merge, production traffic
change, public deployment, permanent-ledger mutation, physical deletion, credential
rotation or Graph Neural Retrieval.

Production retrieval remains lexical. Source PR #19 remains draft, open and unmerged.
The 107 points remain evaluation-only pending proposal and carry no canonical,
candidate-release or production authority.

M23.6.3 still requires a fresh read-only Qdrant preflight proving the target collection
is green and empty, followed by explicit immediate operator approval for the first
upsert. No earlier statement or milestone transition grants that write authority.
