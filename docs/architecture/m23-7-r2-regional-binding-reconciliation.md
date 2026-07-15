# M23.7 Repair R2.1 Live Regional Binding Reconciliation

Issues: #465 and parent #463.

## Accepted implementation and evidence chain

The R2.1 regional path was implemented through PR #466, repaired for omitted empty sparse-vector metadata through PR #470, and accepted against real live evidence through PR #471.

Accepted identities:

- implementation PR #466 merge: `603ce203a7f3a93c8211affa6550ceeefc6b0431`;
- metadata hotfix PR #470 exact head: `237b64d4f42d586112dc44831ad4d406dfdf8dc8`;
- metadata hotfix merge: `7354a8d6ac8f550478e27f3661e4a79f01843af6`;
- live acceptance PR #471 exact head: `afb64ab41d778866760f50db843c3d7157e8312c`;
- live acceptance merge: `1174be8d67415cd9f2280f89dfdb6305adfd24f9`;
- live receipt SHA-256: `aa56655d19cb617177bd8e4708c02e1cd6ce02189fcfee32a5b397ef0eba67db`;
- digest-bound acceptance record SHA-256: `bcffb10590a4118c4c77a23d1c35bf618d8f0f87bf6ac27987fe862fea3c9da2`.

## Exact-head workflow acceptance

PR #471 exact head `afb64ab41d778866760f50db843c3d7157e8312c` passed:

- M23.7 Repair R2.1 Regional Binding run `29437334338`;
- CI run `29437334448`;
- M17 Architecture Canon Acceptance run `29437334461`;
- M18 Graph v2 acceptance run `29437334593`.

All four runs concluded successfully before expected-head merge.

## Reconciled live outcome

The placed Worker path measured:

- Workers AI binding: 227 ms;
- Qdrant batch: 554 ms;
- Worker-internal shadow: 781 ms;
- canonical maximum: 1200 ms;
- margin: 419 ms;
- Cloudflare placement: `local-NRT`.

Probe identity, exact rankings and read-only collection identity remained equivalent to the direct batch path. Error, ACL-violation and output-influence rates were zero. The canonical budget was unchanged and no inflation was used.

Therefore `blocked_pending_latency` is cleared by new live evidence.

`blocked_pending_retrieval_quality` remains the only repair blocker and belongs to R3 bounded live re-observation. R3 becomes the next legal workstream only after this reconciliation merges and the diagnostic Worker is deleted.

## Authority and lifecycle boundary

Production retrieval remains lexical. Candidate mode and semantic answer serving remain disabled. Promotion eligibility remains false. A new explicit promotion decision is still required after R3.

Source PR #19 remains draft, open and unmerged at `deb3ad1e631c2149183d10561fbceb0a1848a989`.

The isolated non-production Worker `knowledge-engine-m23-7-r2-binding` must be deleted after this reconciliation merges. Issues #465 and #463 remain open until deletion is independently confirmed and recorded.

No production pointer, R2 object, Source, Qdrant write/delete, permanent ledger, public Graph Explorer, live traffic, answer-serving or promotion mutation is authorised.

Production mutation dispatched: false.
