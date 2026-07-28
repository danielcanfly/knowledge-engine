# M26.PA.4 Real Verified Answer and Citation Gate

M26.PA.4 is a bounded live verification gate for non-final answer candidates. It is
unlocked only by the accepted M26.PA.3 status
`m26_pa_3_live_provider_execution_accepted` and Daniel Huang's exact PA4 owner
decision recorded in `pilot/m26/m26-pa-4-owner-decision.json`.

The implementation freezes a 12-item real benchmark population before the live run.
Each item binds to the accepted M25 production release, the semantic-inputs artifact,
the Qdrant production collection, a source id, a section id, a passage locator id, and
the passage text digest. The population artifact stores no passage body, no provider
response text, no vectors, and no secrets.

## Live Gate

The main-branch live job is triggered only by the marker
`[m26.pa4-real-verified-answer-authorized-attempt-2]`.

For each benchmark item the live job:

- reads the accepted production pointer, manifest, and semantic inputs through read-only
  R2 credentials;
- scrolls the accepted production Qdrant collection with vectors disabled;
- verifies the frozen 12 locators against both R2 semantic-inputs and Qdrant payloads;
- sends only an ephemeral per-item passage to MiniMax M3;
- records provider request and response hashes, usage, locator ids, claim hashes, support
  verdicts, repair use, abstention outcomes, and security findings;
- refuses to persist raw corpus text or raw provider response text.

The provider is allowed at most two calls per benchmark item, including one bounded
repair attempt. A non-abstained material claim is accepted only when the claim text from
the provider is an exact passage span in the cited locator. Unsupported claims, missing
locators, unresolved conflict or stale temporal conditions, privacy/security findings, or
exhausted repair budget force abstention.

Attempt 2 preserves the original useful-answer floor instead of accepting pure
abstention: at least 8 of the 10 candidate-eligible cases must become ready candidates,
the 2 mandatory-abstention cases must abstain, citation support must remain 100%, and
unsupported accepted material claims must remain 0.

## Attempt-2 Diagnostic Contract

Both success and failed-closed receipts use strict v2 schemas and self-digests. A final
threshold failure must preserve the sanitized per-case diagnostics collected before the
threshold is applied, including result class, safe reason codes, repair class, terminal
status, provider call count, token usage, output length and hash, claim/support/citation
counts, locator identity, and persistence-denial booleans.

Receipts also include aggregate reason-code, result-class, and terminal-status
histograms plus population-fitness diagnostics. Population fitness records only case
identity, requested claim type, passage length/hash, selected-span existence, selected
span hash, and locator identity. It never stores raw provider response text, raw corpus
text, complete prompts, user queries, answer text, secret values, or vectors.

## Denied Authority

This gate does not authorize production answer serving, public or shadow traffic,
production pointer mutation, source/foundation/release mutation, Qdrant or R2 writes,
canonical writes, vector persistence, secret persistence, raw corpus persistence, or a
verified-final answer label.

## Acceptance Boundary

The implementation PR is not acceptance. PA4 can reach
`m26_pa_4_verified_answer_citation_gate_accepted` only through a separate reconciliation
PR that binds the exact main-branch live run, artifact id, receipt digest, benchmark
population digest, provider-call count, terminal outcomes, and zero-mutation record.
