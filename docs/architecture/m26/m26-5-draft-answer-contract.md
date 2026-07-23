# M26.5 Draft Answer Contract and Citation Binding

M26.5 is a synthetic-only contract stage. It consumes M26.4 provider-mock replay records and produces non-final draft-answer packages with claim-level citation bindings.

## Authority boundary

M26.5 does not call a live provider, use credentials, use provider SDKs, bind real corpus data, invoke semantic or hybrid serving, stream answers, serve production answers, or mutate Source, Foundation, release, production pointer, R2 production, Qdrant or canonical identity surfaces.

The only newly allowed operation is deterministic draft-answer contract assembly from M26.4 safe replay records.

## Inputs

- M26.4 provider replay record.
- M26.4 replay citation bindings.
- M26.4 privacy review identity.
- M26.3 context package and context manifest digests.

## Outputs

- `non_final_draft_answer` for safe draftable replay records.
- `non_final_draft_answer_with_warnings` when conflict or prompt-injection diagnostics are preserved.
- `abstain_propagated` when M26.4 replay is not safe for M26.5.
- `privacy_block_propagated` when M26.4 privacy review blocks output.

All outputs are draft-only and explicitly non-final. They cannot be treated as verified final answers or production answers.

## Citation-binding rules

Every emitted claim must have at least one binding. Every binding must include:

- binding ID;
- claim ID;
- replay citation ID;
- selected passage ID;
- context manifest SHA-256;
- context package SHA-256;
- provider replay SHA-256.

The draft stage fails closed if a citation ID is not present in the M26.4 mock draft citation list, if a binding lacks selected passage identity, or if a claim references a missing binding.

## Abstain and privacy propagation

Abstain and privacy-block replay records cannot emit claims, answer text or citation bindings. They are propagated as non-production packages with diagnostics only.

## Security rules

Prompt-injection text remains evidence-only and is not copied into draft claims. Conflict diagnostics are preserved as diagnostics. Secret-like or privacy-blocked M26.4 outputs remain blocked and do not become draft claims.

## M26.6 boundary

M26.5 prepares M26.6 only after reconciliation records `m26_5_draft_answer_contract_accepted`. M26.6 may start only as synthetic answer evaluation and refusal-gate work. It still cannot call live providers, bind real corpus data or serve production answers.
