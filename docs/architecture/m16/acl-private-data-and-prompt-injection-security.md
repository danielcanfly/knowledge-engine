# M16.2 ACL, Private Data, and Prompt-Injection Security

M16.2 adds a deterministic adversarial validation layer on top of the M16.1 security contracts. It evaluates access and content-safety decisions without storing attack text, changing ACLs, or mutating Source or production.

## Exact baseline

- Engine: `02a8cf56099156cdf660544cd9d386569c048958`
- Canonical Source: `2126db2ed4d372d3d61464fe31a86fc0243a1f24`
- Production release: `20260708T040116Z-69a9f445699a`
- Production manifest: `2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb`
- Production pointer: `38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5`

Every case and report is tied to this identity. Identity drift blocks the case and cannot authorize access.

## Security layers

The closed propagation chain is:

`source_fact → claim → concept/page → artifact → retrieval → citation → answer`

A downstream audience may remain equal to or become narrower than its upstream audience. It may never become broader. A requester must have privilege at least as restrictive as the requested output audience.

## Test families

The evaluator covers:

- ACL propagation;
- requester privilege;
- private-data exposure;
- secret leakage;
- prompt instruction override;
- system-prompt extraction;
- role and tool spoofing;
- citation fabrication and restricted citation use;
- unsafe private fallback;
- benign controls.

Adversarial payloads are represented by closed indicator codes. Raw prompts, answers, excerpts, credentials, IPs, hosts, object URIs, and arbitrary exception strings are not fields in the contract.

## Decision behavior

Every case declares an expected decision and reason. The evaluator derives an observed decision from exact identity, evidence presence, audience propagation, requester privilege, and closed attack indicators.

A security report passes only when every malicious case is blocked for the expected reason and every benign control remains allowed. Missing, drifted, or contradictory evidence is fail-closed.

## Independent gates

The report exposes deterministic gates for:

- ACL propagation;
- privacy;
- prompt injection;
- citation integrity;
- requester privilege;
- evidence completeness;
- no-write authority.

Results and gates use stable ordering. The report uses canonical JSON and SHA-256 identity, and digest mismatch detects tampering.

## Authority boundary

M16.2 rejects any attempt to enable:

- ACL mutation;
- Source write or Source PR;
- correction-candidate dispatch;
- production or pointer mutation;
- cache purge;
- R2 mutation;
- credential rotation;
- promotion or rollback;
- permanent-ledger append.

Issue #30 remains open and untouched. M16.2 is a test shield, not a permission editor or incident executor.
