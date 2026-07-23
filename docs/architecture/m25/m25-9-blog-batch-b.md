# M25.9 Blog Pilot Batch B

Status: `implementation_in_progress_exact_batch_b_not_yet_bound`

## Objective

Construct the remaining 78 English blog sources as the exact complement of the accepted Batch A population. Batch B must reproduce the complete pinned 156-source corpus and accepted A/B inventories before it may materialise sources or structural candidate nodes.

## Accepted baseline

- knowledge-engine predecessor: `6286a21d67164ded2cb677618ffe95db8db10938`
- upstream repository: `huaihsuanbusiness/daniel-blog`
- upstream commit: `97821b6547ce3c0b8b8acf11cbbf4795684df458`
- master inventory: `ee8589e4e2ce19005507fc5b9f3aa47d3c0320ab34848e81948c5cdaad7f729e`
- Batch A inventory: `734b6d5d346ad1e283d8d420332e6dab0f6c77074f7a4ed445bbcba62144f879`
- Batch B inventory: `f58b1be75093ad4f530e5317c35055a9b1cc21d56cef6b921550fd544b976988`

The Batch B executor rejects the run before output construction when any of these three inventory digests changes.

## Population contract

The executor must prove:

- master population = 156;
- Batch A = 78;
- Batch B = 78;
- Batch A intersection Batch B = 0;
- Batch A union Batch B = master population;
- missing = 0;
- canonical formal series = 24;
- parent collections including standalone = 25;
- every real series remains within one batch;
- canonical series title and series ID remain one-to-one;
- every Batch B article reaches `acquired_verified`.

## Construction

The executor reuses the accepted parser, Git tree/blob acquisition, series catalog, alias convergence, whole-series partition and structural graph builder. It then:

1. regenerates and validates the accepted master and A/B inventory digests;
2. selects only the exact Batch B complement;
3. writes 78 immutable Markdown snapshots;
4. constructs Series, Article and H2/H3 Section nodes;
5. constructs `part_of`, `contains` and `precedes` edges;
6. verifies Article and Section source locators;
7. verifies Series-node source-article lineage;
8. emits a signed Batch B candidate receipt and exact-head evidence.

## Candidate status

The generated graph is structural candidate data. It is not yet queryable through the production Knowledge Engine and does not appear in the internal Sources or Graph interfaces until a separately authorised Source admission, candidate release, indexing and deployment sequence completes.

## Authority boundary

This construction does not permit:

- Source write, Source PR creation or Source merge;
- semantic claim promotion or automatic concept merging;
- candidate deployment;
- R2 or Qdrant production mutation;
- production release, pointer, traffic or credential mutation;
- M25.9B human-decision closure;
- M25.9C approved-subset adoption.

The next legal action after successful exact-head construction is to bind the exact Batch B inventory, candidate-node, candidate-edge and receipt digests to Daniel's review authority.
