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
