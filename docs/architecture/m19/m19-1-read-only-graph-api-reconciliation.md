# M19.1 Read-only Graph API Reconciliation

Status: complete  
Issue: #267  
Production mutation dispatched: false

## Merged identities

| Boundary | Identity |
|---|---|
| Engine main before M19.1 | `f2957a9ce5c38f2af6f13b27c3ed55e0b67b431c` |
| Implementation PR | #268 |
| Implementation exact head | `1e4813c939e65052c83beb2b9a6a3d7e4160e198` |
| Implementation merged main | `848a4bfa6e87c170fd7ed50bdbde440d9fa09440` |
| Source main | `a6ba738d910d01d2ae99b1968f0831989934c549` (unchanged) |
| Foundation main | `e5ef644053d34e89c70d2ceb37521e1c59234832` (unchanged) |

PR #268 was squash-merged with expected head SHA
`1e4813c939e65052c83beb2b9a6a3d7e4160e198`. Issue #267 remained open until
this independent reconciliation change.

## Delivered contract

M19.1 adds six authenticated GET-only endpoints over the verified active Runtime
release: capabilities, release identity, search, node, one-hop neighborhood, and
bounded overview. OpenAPI scanning proves that the Graph surface has no POST,
PUT, PATCH, or DELETE operation.

The service validates graph schema and release identity, rejects renderer fields,
unknown audiences, duplicates, and missing endpoints, then filters nodes by the
principal before any serialization. An edge is returned only when its own
audience and both endpoints are authorized. Unauthorized and nonexistent node
lookups use the same 404 response, preventing existence disclosure.

The response contract preserves exact release, manifest, Source, Foundation,
concept, and edge identities while omitting provenance object paths, claim and
review identities, qualifiers, and raw evidence. Description, tags, aliases,
source path, result counts, one-hop depth, payload bytes, and execution time are
bounded. A verified legacy release without graph v2 advertises the missing
capability and cannot serve graph data.

## Changed-file reconciliation

Implementation PR #268 changed exactly:

- `.github/workflows/m19-1-read-only-graph-api.yml`;
- `docs/architecture/m19/m19-1-read-only-graph-api.md`;
- `src/knowledge_engine/api.py`;
- `src/knowledge_engine/m19_graph_api.py`;
- `tests/test_m19_1_graph_api.py`.

No Source or Foundation file changed. There were no PR comments, submitted
reviews, or unresolved review threads before the expected-head merge.

## Validation evidence

Local validation at the implementation content passed:

- full `make ci`: 853 tests passed;
- targeted Graph API and regression suite: 32 tests passed;
- ruff, compileall, diff, and OpenAPI read-only scans passed.

All workflows associated with exact implementation head
`1e4813c939e65052c83beb2b9a6a3d7e4160e198` succeeded:

- CI run #582;
- M19.1 Read-only Graph API run #1;
- M18.6 Runtime compatibility run #5;
- M18 Graph v2 acceptance run #18;
- M17 Architecture Canon Acceptance run #15;
- R2 Canary run #229;
- R2 Release Integration run #422.

## R2 and production boundary

No production workflow, candidate or production publication, production
promotion, or production-pointer update was dispatched. No credential,
permanent-ledger, lifecycle, or rollback state changed.

Repository-wide R2 checks ran automatically because `api.py` changed. The
release integration used test environment authentication and run-specific
channel `ci-lifecycle-29226991805-1`, created two test releases, exercised ACL
and rollback, and reported `R2_RELEASE_INTEGRATION_PASSED`. Its mandatory
`finally` cleanup deletes the test pointer and every generated release object;
the successful run emitted no `R2_CLEANUP_ERRORS`. This was isolated CI
validation, not a production or retained R2 mutation, and M19.1 did not manually
dispatch it.

## Exclusions

M19.1 did not add Graphology, Sigma, a browser application, layouts,
communities, coordinates, multi-hop expansion, export, editing, Source mutation,
candidate publication, production activation, embeddings, or Graph Neural
Retrieval. M19.2 may start only after this reconciliation passes exact-head CI,
merges with its expected head SHA, and closes issue #267.
