# M26 AQ Final BB03 Forensic

## Verdict

`CORPUS_BACKED_RETRIEVAL_DEFECT`

BB03 was not an unsupported or out-of-domain question. The handoff evidence shows
that retrieval produced semantically plausible candidates, but the canonical
runtime discarded them before provider synthesis because the Chinese question had
no literal token overlap with the English corpus passages.

## Observed Failure

Case: `CORPUS-BB03`

Question:

> 如果客戶明明都承認問題存在，為什麼市場仍然可能完全不動？請用旅宿業者的實際經驗解釋「有痛點」和「願意改變／願意採用」之間還差了哪些條件。

Observed outcome in `m26-aq-targeted-live-closure.json`:

- `status`: `owner_only_safe_abstention`
- `answer_text`: empty
- `provider_call_count`: `0`
- reason: `LOW_RETRIEVAL_SUPPORT`
- `selected_evidence_count`: `0`
- `candidate_count_by_channel`: `dense=8`, `lexical=0`, `seed=8`, `combined_unique=8`

The important signal is the mismatch between nonzero semantic candidates and
zero selected evidence. The runtime reached a pre-provider safe abstention
instead of giving the semantic evidence a chance to be verifier-bound.

## Corpus Sufficiency

The same targeted closure evidence contains `CORPUS-BB01`, which is answered
from the hospitality/founder corpus context using passages from:

- `daniel_blog_en__after-the-pause-02`
- `daniel_blog_en__after-the-pause-03`

That answer covers the same business reality BB03 asks about: a hospitality
concept can be compelling while still failing to move the market because the
conditions for adoption are harder than admitting a pain point. The cited
material supports requirements such as capital structure, legal structure,
investor patience, market education, credibility, early supply, international
trust, and execution feasibility.

This is enough to classify BB03 as corpus-backed. The failure was not lack of
knowledge; it was an admission/selection defect in the canonical path.

## Root Cause

`m26_pa7_arbitrary_query_runtime._has_meaningful_overlap` required literal token
overlap unless the question matched strict identifier handling. For BB03, the
question was Chinese while the relevant corpus material was English. Dense
retrieval found candidates, but lexical overlap remained zero, so the runtime
returned `LOW_RETRIEVAL_SUPPORT` before provider invocation.

## Repair

The canonical runtime now keeps exact/random identifier questions strict, then
allows multi-passage evidence with explicit semantic retrieval channels or
semantic retrieval metadata to pass admission even when literal overlap is absent.

This repair is deliberately narrow:

- It does not add a new patch package or package-level monkeypatch.
- It does not hardcode BB03 or question wording.
- It does not weaken exact identifier, out-of-domain, citation, or unsupported
  claim controls.
- It only admits evidence that already carries semantic channel/metadata support
  and has enough passage/source quality to proceed to the existing verifier-bound
  answer path.
