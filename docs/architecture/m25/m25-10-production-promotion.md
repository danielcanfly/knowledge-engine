# M25.10 Production Promotion

Status: `owner_authorized_m25_10_production_promotion`

## Authority

Daniel authorized M25.10 production promotion on 2026-07-24 after the live
candidate deployment and owner-authenticated smoke checks accepted release
`m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043`.

The authorization grants:

- verification of the accepted candidate channel `candidate-blog-m25-10`;
- creation of an immutable production-authorized manifest for the accepted release;
- compare-and-swap mutation of `channels/production.json`;
- read-only verification of the existing M25.10 Qdrant candidate collection;
- rollback to the previous production pointer if post-promotion verification fails.

The authorization still denies Source writes, Access policy mutation, credential
creation, DNS mutation, Pages or Worker redeployment, and public production
traffic mutation without an explicit public traffic target.

## Target Identity

- Source SHA: `5250f8422f4fa08c1f3dc84840dc756850817635`
- Engine SHA: `fe499db2e043209bfa4c2390d513c5dc579727a2`
- Release ID: `m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043`
- Candidate manifest SHA-256:
  `f8e2a2f4b775e053bed93f3379f2aa6decd62b36e32380de0aff16caf14f18f3`
- Previous production pointer SHA-256:
  `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

## Promotion Mechanism

The production workflow reads `channels/candidate-blog-m25-10.json`, verifies it
points to the exact accepted manifest, then reads and validates the candidate
manifest. The candidate manifest must still be bounded as candidate-only:
`production_pointer_authorized=false` and
`public_production_traffic_authorized=false`.

The workflow derives a new immutable production manifest at:

`releases/m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043/promotion/m25-10-production-manifest.json`

That manifest keeps the accepted release identity and artifact hashes, changes
`status` to `production`, sets `production_pointer_authorized=true`, and keeps
`public_production_traffic_authorized=false`.

The final pointer write uses R2 conditional `If-Match` against the currently
observed `channels/production.json` ETag. If the production pointer is neither
the expected previous SHA nor the already-promoted target, the workflow fails
without promoting.

## Runtime Boundary

This promotion does not redeploy the internal candidate runtime and does not
create a public M25 route. The accepted authenticated endpoint remains:

`https://m24-internal.danielcanfly.com/api/m25/query?q=harness`

Public production traffic remains unchanged until a public hostname/path and
traffic policy are explicitly authorized.
