# M25.9 Blog Pilot Batch A

Status: `implementation_in_progress_exact_inventory_not_yet_bound`

## Goal

Ingest the complete English article population from Daniel's blog without omission. The corpus is split into two equal governed batches of 78 sources. Batch A starts with immutable acquisition and deterministic structural-node generation.

## Canonical source

- repository: `huaihsuanbusiness/daniel-blog`
- commit: `97821b6547ce3c0b8b8acf11cbbf4795684df458`
- selector: `src/content/blog/*/en.md`
- expected population: 156

The source Git commit and Git blob SHA identify the immutable bytes. The public site is a presentation surface and may lag the repository counter.

## Population contract

The builder must prove:

- master inventory = 156;
- Batch A = 78;
- Batch B = 78;
- A ∩ B = 0;
- A ∪ B = master population;
- missing = 0;
- every real series stays inside one batch;
- standalone articles may be assigned individually;
- every article reaches `acquired_verified` or the run fails.

If an exact 78/78 whole-series partition cannot be found, the run fails closed and prints the series population. It must not silently split a real series.

## Source construction

Each source record contains:

- stable article and series identities;
- canonical URL;
- upstream repository, commit, path and Git blob SHA;
- SHA-256 of the complete Markdown bytes;
- title, description, publication date, categories and tags;
- ownership, licence, trust and public audience;
- terminal acquisition state.

Batch A also materialises all 78 Markdown files as immutable evidence snapshots.

## Candidate nodes

This phase creates only deterministic structural candidates:

- `Series` nodes;
- `Article` nodes;
- H2/H3 `Section` nodes;
- `part_of`, `contains` and `precedes` edges.

Every article and section node points to the exact upstream commit, path and source line range. These are structural nodes, not automatically promoted semantic claims.

## Authority boundary

This phase does not permit:

- semantic claim promotion;
- automatic concept merging;
- Source write, Source PR creation or Source merge;
- candidate deployment;
- R2 or Qdrant mutation;
- production release, pointer, traffic or credential mutation;
- M25.9B or M25.9C closure.

After exact-head acquisition succeeds, the generated Batch A inventory digest and candidate graph must be bound to a review authority before any Source write.
