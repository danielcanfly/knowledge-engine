# M14.2 Wiki-First Retrieval Experience

Status: implementation candidate  
Parent: #190  
Slice: #192  
Depends on: M14.1 #191  
Engine baseline: `249a0a7d6e111392a99678daf170196ac518d298`

## Purpose

M14.2 upgrades runtime retrieval from concept-level term matching into a deterministic wiki-first pipeline. The wiki release remains the primary product surface. Raw evidence is not searched unless a later governed contract explicitly authorizes it.

## Section document model

The compiler splits every approved Markdown concept at headings and emits one lexical document per non-empty section.

Each section contains:

```text
concept_id
section_id
x_kos_id
title
section_title
description
excerpt
body
audience
path
terms
```

`section_id` is deterministic:

```text
{concept_id}#{normalized-heading}
```

Duplicate headings receive deterministic numeric suffixes. A document without headings becomes `{concept_id}#overview`.

Existing releases with concept-level lexical documents remain readable. Runtime normalizes those records to an overview section without mutating the release.

## Lexical stage

The lexical score is decomposed into stable components:

- concept title, weight 4;
- section title, weight 3;
- concept description, weight 2;
- section body, weight 1;
- legacy term-list fallback for older releases.

Tie-breaking is deterministic by total score, concept ID and section ID.

## Optional semantic stage

Semantic contribution is accepted only from an artifact with the exact schema:

```text
knowledge-engine-semantic-index/v1
```

An absent or incompatible semantic artifact contributes nothing and does not fail the query. A compatible malformed artifact fails closed. Semantic search cannot broaden audience or activate raw fallback.

M14.2 defines the runtime hook and deterministic score contribution. It does not require every release to carry semantic artifacts.

## Graph expansion

The compiler derives graph edges from actual Markdown links between approved concepts. Runtime expands one hop from the highest-ranked authorized seed concepts.

Graph expansion rules:

1. seed results must already pass audience filtering;
2. the neighbor graph node must pass audience filtering;
3. the selected neighbor section must pass audience filtering;
4. expansion receives a bounded graph score;
5. expansion provenance records the seed concept;
6. hidden nodes never appear in results or citations.

Edges are traversed as adjacency for retrieval while retaining their compiled `links_to` identity.

## Retrieval trace

The internal runtime trace reports:

```text
strategy
stages
query_term_count
section_document_count
candidate_count
selected_count
acl_filtered_count
semantic_available
semantic_used
graph_seed_count
graph_expanded_count
graph_used
raw_fallback_allowed
raw_fallback_used
raw_fallback_reason
```

The strategy is `wiki_first`. This trace remains internal and is not copied into the public M14.1 answer envelope.

## Raw evidence fallback

M14.2 hard-codes:

```text
raw_fallback_allowed: false
raw_fallback_used: false
raw_fallback_reason: disabled_by_governance
```

There is no URL input, connector invocation, arbitrary object-prefix scan or hidden fallback branch in the retrieval modules.

## Release loading

Runtime loads artifacts by manifest `kind` rather than a hard-coded file location. Required runtime artifacts are:

- lexical index;
- graph;
- provenance.

A semantic index is optional. Artifact hashes, byte lengths, release-prefix confinement, channel-pointer race detection and last-known-good behavior remain unchanged.

## Governance boundary

M14.2 reads only the active immutable release. It performs no Source write, release creation, production mutation, rollback, ledger append or physical deletion.
