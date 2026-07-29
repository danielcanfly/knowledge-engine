# M26.PA.5 Controlled Internal Shadow Pilot Gate

Status: `m26_pa_5_blocked_pending_owner_approval`

PA.5 is unlocked only by the accepted M26.PA.4 reconciliation status
`m26_pa_4_verified_answer_citation_gate_accepted`, recorded by acceptance digest
`0581fc85a34b106c3dce5ec9c27adc3c215a87008f30384da7f574bfcbf13ac7`.

This implementation gate defines the strict contract for the real 200-500 question
controlled internal shadow pilot. It does not execute the pilot, claim acceptance, or
authorize any live calls before Daniel approves the exact PA.5 envelope.

## Owner Gate

Daniel must explicitly approve:

- exact implementation PR and head SHA
- exact predecessor acceptance digest
- frozen population count and digest
- reviewer principals and reviewer types
- adjudicator identity
- execution duration/window
- provider/model and credential environment
- maximum calls and total spend
- quality, citation, abstention, latency, cost, and disagreement thresholds
- incident stop conditions
- authenticated internal/shadow-only boundary with no public answers or production serving

These values must not be inferred or auto-selected by code, CI, or an agent.

## Population Plan

The recommended minimum population is 200 real questions:

- 90 direct grounded factual questions
- 30 provenance and source-trace questions
- 20 cross-document comparison questions
- 20 graph/navigation questions
- 15 conflict and temporal-freshness questions
- 15 abstention/no-answer questions
- 10 prompt-injection, privacy, or adversarial questions

Each frozen question must include a stable question ID, natural-language text, locale,
intent, difficulty, expected evidence family or abstention class, construction source, and
question digest. Placeholder questions, formula-generated scores, invented reviewer IDs,
and synthetic provider receipts presented as live evidence are forbidden.

## Population Freeze Preparation

The non-live preparation artifact is `pilot/m26/m26-pa-5-frozen-population.json`,
with manifest `pilot/m26/m26-pa-5-population-manifest.json`. The frozen population is
constructed deterministically from accepted local corpus, provenance, graph, and release
identities, and it records only question text, stable IDs, source identities, strata, and
digests.

This preparation does not execute PA.5 provider calls, generate answers, run review,
use public traffic, or mutate R2, Qdrant, Source, Foundation, release, production
pointers, or canonical serving state. Daniel must still approve the exact population
digest and the remaining PA.5 live pilot envelope before any pilot execution.

## Review Plan

Each question requires at least two independent reviews. Reviewer principals must identify
their type as one of:

- `human`
- `independent_model`
- `deterministic_verifier`

Human review is required for all disagreements and for at least a stratified 10% sample.
Blocking disputes require Daniel or another explicitly named adjudicator.

## Evidence Contract

The pilot receipt schema requires complete population accounting and per-question evidence
for authenticated execution identity, question and population identity, retrieval trace and
evidence bundle identities, provider request and usage metadata, answer/claim/citation/
repair/warning/abstention status, actual latency and cost, reviewer assignments and
timestamps, reviewer decisions and reason codes, disagreement status, and adjudication
status.

The receipt may preserve only bounded metadata, hashes, IDs, counts, verdicts, reason
codes, timings, and cost values. It must not persist raw provider response text, raw corpus
text, full prompts, secret values, vectors, unbounded logs, or public answer payloads.

## Boundary

This gate does not authorize PA.5 execution before owner approval. It also does not
authorize PA.6 canary traffic, PA.7 final authority, production answer serving, production
pointer mutation, public answers, public traffic, canonical writes, R2 writes, Qdrant
writes, Source/Foundation/release mutation, raw text persistence, secret persistence,
vector persistence, or `m26_closed`.

After an approved and successful PA.5 execution, acceptance still requires a separate
independent reconciliation PR that binds the exact run, artifact, receipt digest, complete
population denominator, reviewer evidence, thresholds, and zero public/production mutation
record.
