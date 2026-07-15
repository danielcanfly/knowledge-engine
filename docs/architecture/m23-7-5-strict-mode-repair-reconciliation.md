# M23.7.5 Strict-Mode Repair Reconciliation

Issue: #432. Parent: #430.

## Observed failure

The first authorised local M23.7.5 live observation reached the exact non-production
Qdrant Cloud collection but received HTTP 400 from the read-only `/points/scroll`
request before any point was sampled.

No Qdrant write or delete, production mutation, answer serving, Source mutation, R2
mutation, pointer change or credential disclosure occurred.

## Root cause and repair

The original client attached server-side filters for release, manifest, audience and
authority payload fields. Those fields were not created as Qdrant payload indexes, so a
Qdrant Cloud strict-mode configuration may reject the unindexed filtering request.

Implementation PR #433 removed the redundant server-side filters from the isolated
collection's read-only scroll and vector-query request bodies. Safety remains fail-closed
because the implementation still verifies:

- exact collection and 107-point count before and after observation;
- collection health, named vector `default`, dimension 1024 and Cosine distance;
- every sampled and ranked point's release ID and release-manifest SHA;
- vector name, vector dimension and embedding model;
- public audience and complete non-production authority flags;
- zero candidate output influence and lexical response authority.

The repair exposes only POST requests to `/points/scroll` and `/points/query`, with no
upsert, write or delete surface.

## Accepted implementation

- implementation issue: #432;
- implementation PR: #433;
- accepted implementation head: `bd5852b084cdf541ce0e6485ccf022146da58659`;
- implementation merge: `9b0173e8820c8fdb12e293d0908096821d571539`.

Accepted exact-head runs:

- M23.7.5 Bounded Live Shadow `29402530228` (run 13), success;
- CI `29402530442` (run 887), success;
- R2 Release Integration `29402530447` (run 600), success;
- M18 Graph v2 acceptance `29402530330` (run 323), success.

No review thread or PR comment remained unresolved at merge time.

## Remaining M23.7.5 gate

This repair does not claim that the real live observation succeeded. Issue #430 remains
open. The local operator must pull main and rerun the same bounded live command. Only a
successful redacted receipt, independently reconciled by expected-head merge, may close
#430 and unblock M23.7.6.

Production mutation dispatched: false.
