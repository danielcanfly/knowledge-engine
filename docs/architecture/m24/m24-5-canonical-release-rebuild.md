# M24.5 Canonical Release Rebuild

P2 rebuilds the Engine release artifacts from the adopted canonical Source SHA
created by the P1 Source adoption.

## Exact Inputs

- Source repository: `danielcanfly/knowledge-source`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`
- Engine builder SHA: `22041bfecd07c9e4b75146ab4d0b83e417e914e8`
- Foundation SHA: `e5ef644053d34e89c70d2ceb37521e1c59234832`
- Release time: `2026-07-20T16:00:00Z`

## Rebuilt Release

The rebuild produced non-production release
`20260720T160000Z-46137c97263e` on channel
`m24-p2-canonical-rebuild`.

The release manifest digest is
`ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`.
The Source snapshot digest is
`9f2fa3df237616e97b6e3bece5f4dfc96a72342ccba2452ee8fe375286d6a451`.

The release contains 20 concepts, 92 sections, 20 provenance records, and
7 source snapshots. Canonical authored relations are represented in
`graph-v2.json`: 20 nodes, 28 total edges, 15 authored edges, and 13 generated
inverse edges.

## Authority Boundary

This rebuild is a derived artifact refresh. It does not authorize production
serving changes.

- production retrieval remains `lexical`;
- semantic promotion remains disabled;
- semantic answer serving remains disabled;
- hybrid retrieval remains disabled;
- no production pointer, R2, Qdrant, credential, or traffic mutation is
  authorized.

P2 is complete when the evidence artifact
`pilot/m24/m24-p2-canonical-release-rebuild.json` is merged with tests.
