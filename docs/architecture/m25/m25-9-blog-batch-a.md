# M25.9 Blog Pilot Batch A

Status: `candidate_acquisition_ready_source_write_not_authorized`

## Goal

Ingest the complete English article population from Daniel's blog without omission. The corpus is split into two equal governed batches of 78 sources. Batch A performs immutable acquisition and deterministic structural-node generation before any Source write.

## Canonical upstream

- repository: `huaihsuanbusiness/daniel-blog`
- commit: `97821b6547ce3c0b8b8acf11cbbf4795684df458`
- article selector: `src/content/blog/*/en.md`
- series catalog: `src/utils/seriesMeta.ts`
- pinned series-catalog blob: `a08a3e025a60da9a35ed3573e1c64a57d26b9201`
- expected population: 156 English articles

The Git commit and each Git blob SHA identify immutable bytes. The public site is a presentation surface and may lag the repository counter.

## Series identity

Series resolution follows the site's production logic and a one-to-one identity convergence rule:

1. Explicit article frontmatter `series` is authoritative for the displayed series title.
2. The pinned `seriesMeta.ts` slug catalog supplies a series key and fallback title when frontmatter omits `series`.
3. When an explicit title matches a normalized catalog English label but its slug is outside the catalog regex, the article converges to that catalog key.
4. An article becomes standalone only when neither source provides a series.
5. A canonical series title and series ID must have a one-to-one relationship.

At the pinned commit this resolves to:

- 24 formal series;
- 2 true standalone articles;
- 25 parent collections including the standalone collection;
- 41 articles whose series is recovered through the catalog fallback;
- 1 explicit-title alias convergence for the From RAG Appendix A article.

The catalog fallback prevents AI Agentic Workflow, Build Your Own MCP Server, MCP Engineering Deep Dive, ComfyUI, OpenClaw and RAG Engineering articles from collapsing into a false standalone bucket. The alias convergence prevents `From RAG to Enterprise-Grade RAG` from splitting into separate catalog-key and title-key series.

## Population contract

The builder must prove:

- master inventory = 156;
- Batch A = 78;
- Batch B = 78;
- A ∩ B = 0;
- A ∪ B = master population;
- missing = 0;
- every real series stays inside one batch;
- only true standalone articles may be assigned individually;
- every canonical series title maps to one series ID;
- every article reaches `acquired_verified` or the run fails.

If an exact 78/78 whole-series partition cannot be found, or any series title/key identity remains split, the run fails closed and prints the conflicting population.

## Source construction

Each article source record contains:

- stable article and canonical series identities;
- series resolution source and series order;
- canonical URL;
- upstream repository, commit, path and Git blob SHA;
- SHA-256 of the complete Markdown bytes;
- title, description, publication date, categories and tags;
- ownership, licence, trust and public audience;
- terminal acquisition state.

The master inventory separately pins the exact series catalog, its Git blob SHA, SHA-256, parsed catalog records and alias-convergence count. Batch A materialises all 78 Markdown files as immutable evidence snapshots.

## Candidate nodes

This phase creates deterministic structural candidates only:

- `Series` nodes;
- `Article` nodes;
- H2/H3 `Section` nodes;
- `part_of`, `contains` and `precedes` edges.

Every article and section node points to the exact upstream commit, path and source line range. Series nodes are generated only after title/key convergence. These structural nodes are not automatically promoted semantic claims.

## Authority boundary

This phase does not permit:

- semantic claim promotion;
- automatic concept merging;
- Source write, Source PR creation or Source merge;
- candidate deployment;
- R2 or Qdrant mutation;
- production release, pointer, traffic or credential mutation;
- M25.9B or M25.9C closure.

After exact-head acquisition succeeds, the converged Batch A inventory digest and candidate graph must be bound to Daniel's review authority before any Source write.
