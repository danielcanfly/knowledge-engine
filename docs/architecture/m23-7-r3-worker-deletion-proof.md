# M23.7 R3 Diagnostic Worker Deletion Proof

Issue: #479. Parent: #474. Next workstream: #478.

## Purpose

This record seals the operational cleanup of the rejected R3 live observation after independent reconciliation. It does not convert the rejection into a pass and does not clear `blocked_pending_retrieval_quality`.

## Accepted control-plane evidence

- Worker: `knowledge-engine-m23-7-r3-observation`;
- Wrangler delete exit code: `0`;
- deployments lookup exit code: `1` with Cloudflare code `10007`;
- versions lookup exit code: `1` with Cloudflare code `10007`;
- workers.dev after deletion: HTTP `404`, platform error `1042`;
- the endpoint no longer serves diagnostic Worker code.

The deletion-proof record SHA-256 is `e8855372892b7b7e39b4b22001982288f5cb3240d971d1d1ccc59d02a08b5856`.

## Bound rejection evidence

- live receipt SHA-256: `43496be4ff84589c74075124e9f70fc7a2b89f2a400c287ebeb35053b1c6e7fe`;
- rejection record SHA-256: `79f27ecf68aa32e855f458e4e30a62932e0a2ea8bc1de522fa5869ed0d4a5ee5`;
- Recall@5: `0.125`;
- MRR@10: `0.049107142857`;
- nDCG@10: `0.095501236426`;
- Worker-internal shadow: `1774 ms`.

## Case-pattern handoff

The redacted case evidence contains eight probes. Six target sections are absent from top 10, two are present in top 10, and only one is in top 5. Incorrect rankings repeatedly collapse onto a small `pilot/harness-theory-part-01` chunk cluster. No raw query is committed.

This pattern is evidence for root-cause investigation, not proof of a specific cause. M23.7-R3.1 must distinguish embedding-input mismatch, instruction or normalization mismatch, vector/payload identity errors, hubness, multilingual alignment failure, target-label validity errors, and request-construction defects.

## Authority boundary

Production retrieval remains lexical. Candidate mode and semantic output serving remain disabled. Promotion eligibility remains false. No production, pointer, R2, permanent ledger, Qdrant write/delete, user traffic or answer-serving mutation is dispatched.

R3 remains incomplete and #474 remains open. The next legal workstream is #478.

Production mutation dispatched: false.
