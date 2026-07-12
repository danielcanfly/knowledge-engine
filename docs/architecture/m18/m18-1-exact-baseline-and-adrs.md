# M18.1 Exact Graph Baseline and ADRs

Status: baseline contract for issue #249  
Recorded: 2026-07-12 UTC  
Production mutation dispatched: false

## Exact repository identities

| Boundary | Identity |
|---|---|
| Engine main | `5a375d616f7d14a3e609bdb317bbc93e222e5924` |
| Source main and build input | `2126db2ed4d372d3d61464fe31a86fc0243a1f24` |
| Foundation main | `608963e2f15e3176e3f80851bf51449411d256da` |

Production release, manifest, and pointer identities were checked against the existing governed baseline and were not changed. This document intentionally does not duplicate those values.

## Current Source/compiler baseline

| Measure | Value |
|---|---:|
| concepts | 5 |
| sections | 28 |
| graph nodes | 5 |
| concept-to-concept edges | 0 |
| provenance records | 5 |
| orphan nodes | 5 |
| public concepts | 4 |
| internal concepts | 1 |
| graph schema | `1.1` |
| lexical schema | `2.0` |
| lexical model | `section` |

The current compiler emits `links_to` only when a standard Markdown link resolves to another concept file. No current body link resolves to another concept, so all five graph nodes are orphans. Wikilinks remain forbidden.

Current retrieval is lexical section scoring, optional term-overlap boosting, and undirected direct-neighbor expansion. The optional semantic index is not embedding similarity. With zero edges, graph expansion adds no concepts.

## Invariants

- Markdown Source remains canonical.
- Foundation defines normative contracts; Source contains reviewed knowledge; Engine validates, compiles, and serves.
- No typed relation is inferred from prose, anchor text, shared tags, or vector similarity.
- No Source, release, pointer, object-store, credential, approval, lifecycle, rollback, or permanent-ledger mutation is authorized here.
- Graph Neural Retrieval remains out of scope.

## ADR-0181-01: canonical relation location

Use one editable truth. Initially, reviewed relation declarations live with Source concept metadata. If density later requires a registry, migration must designate one representation as editable and generate the other. Two editable truths are forbidden.

## ADR-0181-02: ontology ownership

Foundation owns the renderer-neutral base schema and relation semantics. Source pins an exact ontology profile and may contain governed extensions allowed by Foundation. Engine validates and compiles but does not invent semantics.

## ADR-0181-03: tag taxonomy ownership

Foundation defines the taxonomy contract. Source owns and pins the controlled vocabulary and aliases. Free-form or machine-proposed tags remain candidates until reviewed.

## ADR-0181-04: graph versioning

Graph v2 is an explicit capability. Runtime detects it from manifest and artifact metadata, never dates or release names. Existing v1-style releases remain loadable during a bounded compatibility window.

## ADR-0181-05: deterministic edge identity

Edge identity derives from schema version, immutable normalized endpoint IDs, relation type, direction, and normalized semantic qualifiers. Symmetric endpoints are sorted. Titles, list order, coordinates, styling, and renderer state are excluded.

## ADR-0181-06: audience derivation

An edge is at least as restrictive as both endpoints and its supporting evidence. Unknown audience meaning or missing evidence fails closed. Serialization omits an edge if either endpoint is unauthorized.

## ADR-0181-07: v1 compatibility

Graph v2 preserves generic Markdown `links_to` separately from reviewed typed edges. Runtime accepts v1 and v2 during migration, or the compiler emits a documented v1 projection for an inventoried consumer. Old links are never automatically reinterpreted as factual typed relations.

## M18 acceptance contract

M18 fails closed on unknown relation type, missing target, invalid direction or inverse, duplicate edge, alias collision, invalid tag, missing provenance, unapproved relation, ACL broadening, nondeterminism, renderer-field leakage, broken links, or Wikilinks.

Each submilestone records exact base and PR head SHAs, deterministic validation, exact-head workflow evidence, changed-file reconciliation, production-baseline comparison, and mutation status.

## M18.1 exit criteria

- Repository heads and current graph/lexical counts are pinned.
- The seven blocking ADRs are explicit.
- Machine-readable baseline and acceptance data agree with this document.
- Existing checks pass on the exact PR head.
- Governed production baseline remains unchanged.

M18.1 documents the decisions; later submilestones implement them.
