# M26 AQ OOD Relevance Red Tests Spec

Worker: GPT-5-3  
Scope: research + red tests only  
Base head: `9e9bfddd7a141a779adb5c7866e725d64b28ba85`  
Assigned case: GPT-E-BB18

## Root cause

BB18 exposes a gap between citation validity and question relevance. The runtime can accept an answer when all of the following are true:

1. The provider returns compact semantic closure JSON with valid selected evidence IDs and locators.
2. The support quote is byte-exact text from an authorized passage.
3. The claim surface is entailed by that quote.
4. The direct-answer facet is considered covered because the visible answer and support text share generic words such as `launch`.

That is still insufficient for question answering. In BB18, the user asks for the launch date of a nonexistent compound subject: `cobalt-orchid moon-ferry ticketing protocol`. The selected evidence says only that a team was delighted and called a launch a win. The quote is true, citable, and internally supported, but it is irrelevant to the requested subject and attribute.

The current verifier therefore conflates:

- **claim-support correctness**: the quote supports the claim surface;
- **question-evidence relevance**: the evidence establishes the queried subject and requested attribute.

BB18 fails the second condition.

## Required production rule for GPT-5-4

Add a hard stop before accepting provider or deterministic recovery answer candidates:

`QUESTION_EVIDENCE_RELEVANCE_HARD_STOP`

Suggested error code: `M26-PA7-ME-047`.

The hard stop should reject an answer candidate when:

1. The question contains a distinctive compound subject or named/proper noun-like subject.
2. No used evidence passage establishes that subject as a unit.
3. The candidate only overlaps on generic or decomposed terms such as `launch`, `date`, `protocol`, `ticketing`, or `ferry`.
4. The used evidence supports a different proposition than the requested subject and attribute.

This should return safe abstention, with no answer text, no citations, and OOD/relevance telemetry rather than a cited non-answer.

## Evidence relevance metadata expected

GPT-5-4 should expose enough telemetry to diagnose failures without reading the rendered answer:

- extracted question subject phrase, for example `cobalt-orchid moon-ferry ticketing protocol`;
- requested attribute/action, for example `launch date announced`;
- whether the subject phrase appears as a contiguous or normalized unit in used evidence;
- whether only decomposed/common terms matched;
- used evidence IDs and their relevance verdicts;
- final failure code `question_subject_not_established` or equivalent under `M26-PA7-ME-047`.

## Negative controls

The fix must not over-block supported questions:

1. A real in-corpus entity with directly relevant evidence remains answerable.
2. Supported `Harness Theory Part N` questions remain answerable when the used evidence contains the full Part-N entity.
3. Frozen expected answer questions must not be globally converted into OOD abstentions.
4. The hard stop must target subject establishment, not capitalization or unfamiliar wording alone.

## Red tests added

`tests/test_m26_aq_ood_relevance_redtests.py`

Expected status on current base head:

- `test_bb18_nonexistent_protocol_provider_answer_is_rejected_as_ood_relevance`: **FAILS on current head**, because current verifier accepts a quote about a launch win as a direct answer.
- `test_nonexistent_compound_entity_not_answered_from_individual_common_terms`: **FAILS on current head**, because current verifier accepts decomposed word overlap.
- `test_positive_real_in_corpus_direct_answer_remains_verifiable`: should pass.
- `test_frozen_like_part_questions_remain_answerable_when_entity_supported`: should pass for Part 1 and Part 10.

These are red tests only. They intentionally do not implement the production relevance hard stop.
