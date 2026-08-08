# M26 FAS Round #1 Raw Answers

## Typed synthesis

`Durable state preserves progress after a disconnect, while verification checks the final result before acceptance.`

Claim type: `EVIDENCE_SYNTHESIS`

## Typed model explanation

`A model explanation gives generic framing instead of pretending to be a corpus fact.`

Claim type: `MODEL_EXPLANATION`

## Legacy router fallback

`router selection: A router should define permission-first controls before execution [claim_1_ref_1].`

This is the older arbitrary-query surface, kept as a fallback-path regression reference.

## FAS-3 supported multi-source synthesis

`Durable state preserves progress after a disconnect, while completion verification checks the final result before acceptance.`

Claim type: `EVIDENCE_SYNTHESIS`

## FAS-3 unsupported synthesis control

Rejected: `Durable state and verification are the same thing.`

Reason: unsupported equivalence synthesis is not accepted as provenance-grounded synthesis.

## FAS-3 generic model explanation

`A model explanation gives generic framing instead of pretending to be a corpus fact.`

Claim type: `MODEL_EXPLANATION`

Support refs: none required for generic model explanation.

## FAS-4 bounded completeness repair

Initial incomplete answer:

`Durable state preserves progress after a disconnect.`

Repaired answer:

`Durable state preserves progress after a disconnect, while verification checks the final result before acceptance.`

Repair attempts: one bounded repair.

## FAS-4 supported partial answer

`Durable state helps because it preserves progress after a disconnect. Unsupported boundary: the available evidence does not establish verification side, comparison_or_distinction.`

Policy: grounded partial accepted with explicit unsupported boundary.

## FAS-4 unsupported core answer

Result: full safe abstention when no substantial grounded answer can be produced.

## FAS-5 direct fact citation binding

Accepted:

`A router defines explicit request boundaries.`

Rejected controls:

- unrelated support quote for the direct fact
- quote drift that is not exact evidence text
- fabricated locator ID

## FAS-5 synthesis premise citation binding

`Durable state and completion verification separate progress durability from acceptance control.`

The synthesized conclusion is not required to occur verbatim in one source; the cited premises must each contribute to the conclusion.

## FAS-5 model explanation attribution

Generic `MODEL_EXPLANATION` claims remain uncited. A generic explanation carrying corpus support refs is rejected.

## FAS-5 API citation shape

Citation objects retain `citation_id`, `claim_id`, `evidence_id`, `locator_id`, and `source_identity`, and public `answer_claims` retain compatible `citation_ids`.

## FAS-6 integrated local product gate

Cumulative FAS/AQ regression: `217 passed`.

Full local pytest: `2994 passed`.

Ruff, compile checks, JSON validation, diff check, hardcode scan, architecture scan: pass.

Legacy governance: ledger complete; no safety weakening; no citation-integrity weakening.

## FAS-6 unseen generalization set

Question count: 10

Pass summary: `10/10`

Categories:

- single-source direct fact
- multi-source synthesis
- comparison
- why/explanation
- architecture/mechanism
- partial evidence
- unsupported private/specific fact
- OOD/nonexistent control

Representative raw answers:

`A production router inspects the request, applies permission and safety constraints, and selects the downstream path before execution begins.`

`Durable progress records preserve continuity, while final acceptance checks verify whether the result should be trusted.`

`A route selector chooses the handling path, whereas a dependency graph orders tasks and branch or join relationships.`

`Persisted progress helps because it preserves run state after interruption. Unsupported boundary: the available evidence does not establish final checking.`

Unsupported controls:

- private handoff-server token request: safe abstention
- nonexistent Atlas pump protocol torque request: safe abstention
