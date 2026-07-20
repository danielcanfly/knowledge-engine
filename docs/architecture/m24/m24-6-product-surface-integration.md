# M24.6 Product Surface Integration

P3 connects the M24 product-facing surfaces to the exact P2 canonical
candidate release instead of fixtures or planning manifests.

## Canonical Input

- Release ID: `20260720T160000Z-46137c97263e`
- Manifest SHA-256:
  `ef5ee828069731e3e7106e1b12fb82e3a578c377930568410bc78421d1600877`
- Source SHA: `acf78596ace8a7366688ccef72b507204d09d9f9`
- Graph v2 SHA-256:
  `6737dfb3fa9cd4d992c26dce562329c95e06066cd475f97f2fdffdbab8f25abe`
- Lexical index SHA-256:
  `1106857e4eb2438674bc74a074bf81132f54b77f4c5d2dfe52954328b8271b83`
- Provenance SHA-256:
  `0593d6669661df0d639e13b3b93d744b36f6fa934ca4faf7566d05574a573a05`
- Source snapshot artifact SHA-256:
  `c2150569ee59f460f64ece3ddd2deb0c27908d079fb5ac9d91722d0cd3edfd3c`

The bounded local copy is stored under `pilot/m24/canonical-release/` so the
surface tests can exercise the same immutable candidate release without
mutating production storage.

## Integrated Surfaces

P3 verifies five surfaces against the same canonical release identity:

- lexical search using the canonical lexical index;
- provenance source viewer cards and citation locators;
- Concept Wiki pages with typed canonical relationships;
- Sigma/Graphology readiness using the canonical Graph v2 payload;
- Obsidian export with one note per canonical concept and source wikilinks.

Each surface produces digest-bound evidence in
`pilot/m24/m24-p3-product-surface-integration.json`.

## Authority Boundary

P3 is a product-surface integration milestone, not semantic promotion.

- production retrieval remains `lexical`;
- semantic promotion remains disabled;
- semantic answer serving remains disabled;
- hybrid retrieval remains disabled;
- no production pointer, R2, Qdrant, credential, Source, or traffic mutation is
  authorized;
- source viewers expose public source cards, citation locators, and integrity
  identity, not raw evidence text.

Production semantic or hybrid retrieval still requires the semantic promotion
decision gate before any serving change.
