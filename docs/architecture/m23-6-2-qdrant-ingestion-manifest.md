# M23.6.2 Deterministic Qdrant Ingestion Manifest

## Decision

M23.6.2 adds a completely offline dry-run path for the 107 frozen BGE-M3 document
vectors. It verifies immutable evidence and emits a deterministic ingestion manifest plus
Qdrant point payloads. It performs no network operation and carries no write authority.

Production retrieval remains `RETRIEVAL_MODE=lexical`.

## Exact entry baseline

- Engine: `913c8cbb19dd6c7b89b753aecd61afd943e373fc`
- Source: `a6ba738d910d01d2ae99b1968f0831989934c549`
- Foundation: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- M23.6.1 contract: `c28a5d3503b24358c240283cfa1b4629c3e0bfeb6c854f72725481ff4c4a1941`
- evidence ZIP: `1b71c79ed3fddc24abfb510709a08e6a1ad0a3806df23287d2d14a70994f7272`
- semantic artifact: `semantic-35314911af0a514c9f0d64b7cfb1d6d0d2ec88cfa50317fa614e92f21f185f0d`

## Evidence verification

The CLI fails closed unless all of the following hold:

1. The complete evidence ZIP has the exact governed SHA-256.
2. The ZIP has one root and every non-receipt file is covered by `run-receipt.json`.
3. Every receipt byte count and SHA-256 matches.
4. The receipt carries no Qdrant write or production authority.
5. `benchmark-suite.json` contains exactly 107 unique documents and exact Source and
   Foundation identities.
6. `pilot-document-vectors.f32` is exactly 438,272 bytes, little-endian float32,
   107 by 1,024 and L2-normalised.
7. Semantic metadata is immutable, read-only, self-digested and bound to the exact suite,
   model, vector digest and governed semantic artifact ID.
8. Semantic row metadata follows the exact benchmark document order.
9. Semantic vectors are byte-identical to the frozen pilot document vectors.

No row may be manually reordered.

## Evaluation-only membership

Source PR #19 remains draft, open and unmerged. All 107 points therefore use:

```text
evaluation-only-pending-proposal
```

Every payload carries:

```json
{
  "canonical_knowledge": false,
  "candidate_release_eligible": false,
  "production_authority": false
}
```

A later approved Source adoption invalidates this entire plan. Source, lexical,
provenance, Graph v2, semantic vectors and the Qdrant ingestion manifest must all be
rebuilt. There is no partial adoption or point-level promotion path.

## Evaluation release identity

The dry run creates `m23pilot-<24 hex>`, derived from canonical JSON over exact builder
Engine, Source, Foundation, evidence ZIP, benchmark suite, vector, semantic metadata,
semantic artifact, authority contract, model and collection identities.

This is an evaluation release descriptor. It is deliberately not an M23 candidate release
and cannot claim candidate-release eligibility or production authority.

## Point identity and payload

Point IDs reuse the existing M23 UUIDv5 namespace and BGE-M3 model identity. The same
section therefore receives the same point ID across retries and dry runs.

Each point uses named vector `default`, dimension 1,024 and the exact 20-field payload
contract from M23.6.1. The manifest records vector byte offset, row SHA-256 and a content
hash over point ID, payload and vector digest.

Content-hash action is deterministic:

- no existing hash: `insert`;
- equal hash: `skip`;
- different hash: `replace`.

M23.6.2 only records this decision policy. It performs no Qdrant read or mutation.

## Dry-run command

```bash
knowledge-m23-ingestion-plan \
  --evidence-zip /Users/daniel/LLM-Wiki-Evidence/M23.5_Cloudflare_BGE_M3_20260714T164215Z.zip \
  --authority-contract pilot/m23/m23-6-1-authority-contract.json \
  --builder-engine-sha "$(git rev-parse HEAD)" \
  --output /Users/daniel/LLM-Wiki-Evidence/M23.6.2_Real_Dry_Run
```

The output directory must not already exist. The command emits immutable:

```text
ingestion-manifest.json
qdrant-points.json
dry-run-receipt.json
```

There is intentionally no execute flag, Qdrant URL, API key, Cloudflare token or write
flag in this CLI.

## Honest CI boundary

The real evidence ZIP is intentionally not committed and is not mounted in GitHub Actions.
CI therefore builds a structurally equivalent 107-row synthetic archive and proves parser,
row-order, payload, point-ID, hash, replay and adversarial behavior.

Synthetic CI does not prove the real ZIP dry run occurred. The real dry run and its exact
manifest SHA are mandatory M23.6.3 preconditions before the user may authorise any Qdrant
write.

## Acceptance

Run:

```bash
python scripts/m23_6_2_ingestion_acceptance.py \
  --output .artifacts/m23/m23-6-2-ingestion-acceptance.json
```

M23.6.2 may close only after exact-head CI, implementation merge and separate
reconciliation. The next legal action is the real evidence dry run and review. A Qdrant
write remains separately authorised M23.6.3 work.

Production mutation dispatched: false.

## Contract reconciliation

Implementation PR #388 was accepted from exact head
`f9de0b5d7b351b2551f9cf68a36a31f5674acbfa` and merged as
`f9c17811bc23f7af171686805c9c93e0ca7c78bd`.

The accepted head passed all 22 triggered workflows:

| Workflow | Run | Run ID |
|---|---:|---:|
| M23.6.2 Qdrant Ingestion Manifest | 2 | 29384126418 |
| CI | 782 | 29384126447 |
| R2 Release Integration | 523 | 29384126419 |
| R2 Canary | 245 | 29384126394 |
| M16 Security Contract Acceptance | 35 | 29384126428 |
| M16 ACL and Injection Security Acceptance | 34 | 29384126425 |
| M16 Promotion Containment Acceptance | 32 | 29384126416 |
| M16 R2 Object Restoration Acceptance | 30 | 29384126430 |
| M16 Source and Control-Plane Reconstruction Acceptance | 28 | 29384126468 |
| M16 Replay and Recovery Objectives Acceptance | 25 | 29384126445 |
| M16 End-to-End Restore Drill Acceptance | 23 | 29384126409 |
| M17 Architecture Canon Acceptance | 128 | 29384126422 |
| M17 Operator Tooling Acceptance | 21 | 29384126459 |
| M17 Operator Qualification Acceptance | 16 | 29384126432 |
| M17 GA Evidence Matrix Acceptance | 15 | 29384126408 |
| M17 Independent Operator GA Acceptance | 14 | 29384126434 |
| M18 Graph v2 acceptance | 218 | 29384126491 |
| M23.2 Live Intake | 14 | 29384126404 |
| M23.3 Real AI Extraction | 13 | 29384126386 |
| M23.4 Human Review Source PR | 11 | 29384126421 |
| M23.5 Cloudflare Qdrant contract | 10 | 29384126427 |
| M23.5 corrected benchmark contract | 6 | 29384126393 |

The accepted implementation performed no network call, Cloudflare call, Qdrant read or
write, R2 mutation, pointer mutation, Source mutation, Source PR #19 merge, production
traffic change, public deployment, permanent-ledger mutation, physical deletion,
credential rotation or Graph Neural Retrieval. Production retrieval remains lexical.

The real evidence ZIP was not available in this execution environment and the real
107-point dry run was not claimed or fabricated. Synthetic CI cannot replace it. Before
M23.6.3 may request any write approval, an operator must run the accepted CLI against the
exact ZIP, verify the exact evidence digest, inspect all three immutable outputs, record the
real manifest and receipt SHA-256 values, and re-confirm the Qdrant collection is green and
empty through a separately authorised read-only preflight.

M23.6.2 is reconciled as a deterministic planner and validation milestone. The next legal
action is the real evidence dry run and review. Qdrant write authority remains false.
