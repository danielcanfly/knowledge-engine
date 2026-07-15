# M23.7.2 Deterministic Offline Retrieval Evaluation

M23.7.2 consumes the accepted M23.7.1 contract after #409 completed. It evaluates deterministic lexical and candidate ranked evidence for the 24 frozen cases without network, provider, live Qdrant or answer-generation calls.

## Evaluation model

- six balanced query classes;
- ACL-negative and no-answer cases must return no results;
- all positive results carry provenance and ACL evidence;
- Recall@5, MRR@10, nDCG@10, provenance coverage, ACL leakage and no-answer false-positive rate are recomputed from case evidence;
- candidate Recall@5 is compared with lexical Recall@5 under the locked non-regression ceiling;
- evidence and report are self-digested and replay byte-identically.

## Result semantics

`pass` means the controlled offline evidence satisfies the M23.7.1 gates. It does not mean production activation, promotion, deployment or Source adoption is approved. Candidate activation remains false and production retrieval remains lexical.

## Authority boundary

No provider call, semantic judge, live Qdrant read/write/delete, answer generation, deployment, traffic change, Source/R2/pointer mutation, permanent ledger mutation, public Graph Explorer, credential rotation or Graph Neural Retrieval.

Production mutation dispatched: false.
