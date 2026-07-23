# M26.6 Synthetic Answer Evaluation and Refusal Gate

M26.6 is a synthetic-only evaluation stage. It consumes M26.5 non-final draft-answer packages and checks deterministic structure: authority flags, claim-to-citation bindings, selected passage identity, refusal propagation, conflict diagnostics and prompt-injection quarantine.

## Boundaries

The evaluator is not a semantic judge and it does not call a provider. It does not create final answers, verified final answers or production answers. Live provider calls, credentials, provider SDKs, networked model execution, real corpus binding, semantic/hybrid serving, Source mutation, Foundation mutation, release mutation, R2 production mutation and Qdrant mutation are all forbidden.

## Evaluation outcomes

Passing drafts become `evaluation_passed_non_final` or `evaluation_passed_non_final_with_warnings`. The output is still non-final and cannot be shown as a production answer.

Unsafe or insufficient drafts fail closed into refusal states:

- `refusal_abstain_propagated`
- `refusal_privacy_block_propagated`
- `refusal_authority_escalation`
- `refusal_citation_integrity`
- `refusal_prompt_injection_leakage`
- `refusal_fail_closed`

## Refusal gate

The refusal gate preserves abstain and privacy-block decisions from earlier M26 stages. It also catches final-answer escalation, production-answer escalation, missing claim bindings, orphan citations and forbidden prompt-injection leakage. Refusal outputs carry no accepted claims and no accepted bindings.

## Citation and warning policy

Every passing claim must retain at least one binding to an M26.5 citation binding, selected passage identity and draft package digest. Conflict warnings and prompt-injection quarantine flags are diagnostics; they are not instructions. Prompt-injection text remains evidence-only and must not appear as an answer instruction.

## Stop line

M26.6 may prepare M26.7 entry only after post-merge reconciliation records `m26_6_answer_evaluation_refusal_gate_accepted`. M26.6 itself does not authorise production answer serving, verified final answers, real corpus binding or provider calls.
