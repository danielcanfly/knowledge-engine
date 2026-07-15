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
