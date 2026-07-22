# M25.1 Reconciliation and Acceptance

**Accepted status:** `m25_1_architecture_freeze_accepted`  
**Implementation PR:** #1038  
**Implementation head:** `01c6e496e8c5947de02772d9035093b3fc991a4e`  
**Implementation merge:** `8a3e798352f6d16e146b0dc25e1812cc9583cc7f`

## Acceptance result

M25.1 is accepted. The exact entry baseline, reuse map, schema version plan, admission state
machine, authority matrix, adapter boundaries, and digest-bound M25.2 inputs are now part of
Engine main. The implementation was merged with the expected head SHA after all four remote
workflows passed.

## Execution model

ChatGPT completed the repository investigation, architecture, GitHub issue, branch, commits, PR,
CI diagnosis, workflow repair, review, expected-head merge, reconciliation, and evidence assembly.
Codex was not invoked. Daniel did not need to intervene because M25.1 introduced no knowledge,
Source, production, identity-destruction, or scale-authority decision.

## Preserved boundaries

- `intake/v1` remains the sole immutable evidence plane.
- `admission/v1` is control-plane only and does not duplicate raw or normalised source payloads.
- Canonical Source remains the only editable knowledge truth.
- Production retrieval remains lexical.
- Semantic/hybrid serving, production answer serving, production pointer mutation, R2/Qdrant
  production mutation, and large-scale ingestion remain disabled.

## Next legal stage

M25.2 Intake and Batch Orchestrator is the only next implementation stage. It must consume the
M25.1 frozen schemas and examples, reuse M10/M21 contracts through declared adapters, and remain
candidate-only.

Machine-readable acceptance: `pilot/m25/m25-1-acceptance.json`.
