# M24 Source PR #19 Human Review Packet

This advances #974 for `danielcanfly/knowledge-source#19`.

Source PR #19 remains open, draft, and unmerged at head
`deb3ad1e631c2149183d10561fbceb0a1848a989`. This packet does not record human
approval. It converts the review-only proposal into an item-level decision
surface Daniel can review quickly.

## Boundary

- Source PR #19 must not merge as-is;
- canonical Source writes remain unauthorized;
- production retrieval remains `lexical`;
- semantic answer serving, semantic promotion, production pointer changes,
  protected mutations, credential changes, and traffic changes remain disabled;
- approved decisions must later be converted into a separate canonical Source
  adoption PR.

## Existing Canonical Concepts

The current Source `main` concept set contains five concepts:

| x-kos ID | Canonical concept |
| --- | --- |
| `ko_7FHJFQQ11PKPEWC4W25CCBCGZM` | Agent execution paths |
| `ko_7T9Q4M2V8J6K3R5C1N0PWHDBXF` | Agent decision and planning strategies |
| `ko_HW0QBJBSFFJ9SWVXJTDHVV604T` | Six-dimensional map of LLM agent architectures |
| `ko_01JXYZ123456789ABCDEFGHJKM` | Source governance |
| `ko_01JXYZ123456789ABCDEFGHJKQ` | Candidate delivery controls |

Source PR #19 marks every candidate as `probable_duplicate` only because of
shared governed tags. That is weak evidence. It requires human review but does
not prove identity with an existing concept.

## Recommended Review Queue

These recommendations are triage guidance, not final decisions.

| Item | Review ID | Suggested decision | Rationale |
| --- | --- | --- | --- |
| Harness | `m23review_e2847c567565549ea21b89ee7b572d47` | `approve_new` | This is the parent execution-governance concept tying request boundary, task contract, completion gate, authority, and verification together. Existing concepts discuss agent architecture layers but do not name the harness as a governed product/runtime object. |
| Task Contract | `m23review_37d35397ace98d69c00b0e8fe4cb1458` | `approve_new` | The explicit outcome/evidence/constraint contract is narrower than general planning strategy and should anchor goal drift, completion, and review. |
| Request Boundary | `m23review_12cf0442aff36f0400715efe1ee1025a` | `approve_new` | Ingress identity, tenant scope, schema validity, and admission are product/security boundaries, not only architecture taxonomy. |
| Completion Gate | `m23review_ed53fb63ef649af90d2e2f73e85ae5e7` | `approve_new` | The terminal acceptance authority is a concrete harness primitive. Existing verification content is broader and does not own terminal candidate acceptance. |
| Canonical Run Authority | `m23review_8566693dd5241e3269f5038e01394f6b` | `approve_new` | Execution state authority differs from Source governance and candidate delivery; it deserves an execution lifecycle concept if Daniel wants harness operations modeled explicitly. |
| Stopping Policy | `m23review_7c7842b8a5e71c5f7577b26c27e2f73f` | `approve_new` | Stop/wait/complete/fail/cancel rules are reusable across harness execution and should not be hidden inside planning prose. |
| Goal Drift | `m23review_0df0b6cb698712b98425cc2b05265565` | `approve_new` | The failure mode is directly tied to Task Contract and steering; existing concepts mention weak goals but do not preserve goal drift as a first-class object. |
| Steering Control Plane | `m23review_784ebc246b86b22be547d2f4c006ca64` | `approve_new` | Human authority over intent, boundaries, evidence, and escalation is distinct from Source governance and planning strategies. |
| Headless Harness Service | `m23review_ee3af10c8e0f2f6d9fb49c6c7b1f308c` | `approve_new` | A UI-independent execution core is an implementation/product architecture concept, not covered by the existing five canonical concepts. |
| Durable Thread State | `m23review_ce9255a1a87d7f2cc87c88ec26e1dc9a` | `approve_new` | Persistent interaction state across turns is a concrete runtime primitive and should support the Headless Harness Service concept. |
| Item Turn Thread Protocol | `m23review_08f2083f1643842c7266a7fa3e7118b1` | `approve_new` | The typed item/turn/thread model is specific enough to warrant a canonical protocol concept if it is part of product architecture. |
| Harnessability | `m23review_94192ccc4b53c47e32942121da3775c2` | `edit` | Keep the idea, but tighten the definition as a measurable quality attribute before canonical adoption. Suggested title remains `Harnessability`. |
| Agent Loop | `m23review_998e1adb9a6ce64f12a4fc9477eebe30` | `edit` | Existing planning content already covers bounded ReAct loops. Approve only if edited to a harness-specific governed loop with distinct lifecycle semantics. |
| Tool Calling | `m23review_c3b0082d594d591018a417614574b098` | `edit` | The current definition is broad. Prefer an edited concept such as `Tool Call Proposal` if the intended meaning is that tool calls are proposed external operations requiring authority. |
| Verification | `m23review_a91d9910fbd95236a02e5f1bf52a1b27` | `edit` | Existing architecture content includes verification and recovery. Approve only if edited to a harness-specific verification primitive with acceptance authority boundaries. |

## Daniel Review Checklist

For each item, record exactly one decision in Source PR #19:

- `approve_new`: create a new canonical concept later;
- `map_existing`: map to one existing x-kos ID and explain why;
- `edit`: provide an edited title or definition before adoption;
- `reject`: exclude from canonical Source;
- `defer`: postpone with a reason.

Every non-`reject` decision should include provenance notes sufficient to build a
later canonical adoption PR.

## Recommended Closure Condition for #974

#974 should close only after Source PR #19 records explicit decisions for all 15
items with a non-null human actor and reviewed timestamp. Until then, #974 is
materially advanced but not complete.
