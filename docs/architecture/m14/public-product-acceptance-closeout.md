# M14.7 Public Product Acceptance and Closeout

M14 closes only when the public Knowledge OS product is validated as a full user-facing surface rather than a collection of isolated engineering slices.

## Baseline

- Engine main at M14.7 entry: `f4ae4d3469d9fcf734ca3466d4cd98727fa48620`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`
- Parent issue: #190
- Permanent production ledger: #30, remains open and is not appended by M14.7.

## Completed prerequisite slices

M14.7 requires every prior M14 slice to be closed as completed before any parent closeout:

| Slice | Issue | Required capability |
| --- | ---: | --- |
| M14.1 | #191 | Stable public query API and response contract |
| M14.2 | #192 | Wiki-first retrieval with section-level lexical search, graph expansion and governed fallback posture |
| M14.3 | #194 | Citation payloads and source cards |
| M14.4 | #196 | JSON API, standalone chat and embeddable widget interfaces |
| M14.5 | #198 | Audience, security and abuse controls |
| M14.6 | #200 | Immutable feedback and correction intake |

## Product-level acceptance

A public user must be able to:

1. Ask through the public product surface.
2. Receive an `answered` response from the current production release.
3. Inspect release-bound citations and source cards.
4. Submit a bounded correction or feedback signal bound to the exact request, release and public audience.
5. Receive an HTTP 202-style feedback receipt that enters `pending_review` rather than changing Source or production.

The acceptance contract is implemented in `knowledge_engine.m14_acceptance` and exercised by:

- `tests/test_m14_acceptance.py`
- `scripts/m14_public_product_acceptance.py`
- `.github/workflows/m14-public-product-acceptance.yml`

The generated acceptance artifact is deterministic and includes a canonical `artifact_sha256` digest.

## Invariants

M14.7 keeps these boundaries false:

- Source write
- Source package creation
- Source PR creation
- Candidate dispatch
- Production write
- Production promotion
- Rollback
- Physical deletion
- Permanent-ledger append
- Arbitrary URL fetch
- Attachment intake
- Server-side conversation memory
- Automated correction acceptance

The permanent ledger remains open because it is an audit ledger, not the approval surface for M14 public product closure.

## Workflow evidence required before merge

The PR head accepted for M14.7 must be unchanged while all required workflows pass:

- CI
- R2 Canary
- R2 Release Integration
- M13 Three-Batch Acceptance
- M14 Public Product Acceptance

Only after those exact-head checks pass may the PR be guarded-merged with `expected_head_sha`. After merge, #202 may be closed as completed. Parent #190 may close only if M14.7 is merged and no M14 exit criteria remain open.

## Remaining work after M14

M14 does not automate correction acceptance, modify Source from feedback, create curation PRs from every signal, add attachment feedback, persist conversations, add distributed WAF/bot controls or promote a new production release. Those are later governed roadmap concerns.
