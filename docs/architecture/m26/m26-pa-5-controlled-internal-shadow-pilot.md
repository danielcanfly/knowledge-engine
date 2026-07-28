# M26.PA.5 Controlled Internal Shadow Pilot

Status: `m26_pa_5_controlled_internal_shadow_pilot_accepted`

M26.PA.5 records a controlled shadow pilot over a frozen 200-question population. The pilot
is authenticated internal review only. It captures reviewer, quality, citation, abstention,
latency, and cost evidence for every question in the denominator. Public answers remain
forbidden.

## Evidence

- Policy: `pilot/m26/m26-pa-5-shadow-policy.json`
- Frozen questions: `pilot/m26/m26-pa-5-frozen-questions.json`
- Entry contract: `pilot/m26/m26-pa-5-entry-contract.json`
- Contract registry: `pilot/m26/m26-pa-5-contract-registry.json`
- Acceptance: `pilot/m26/m26-pa-5-acceptance.json`
- Implementation: `src/knowledge_engine/m26_controlled_internal_shadow_pilot.py`

The accepted population has 200 questions, three reviewers per question, 184 reviewed
answers, 10 reviewed abstentions, and 6 hold-for-repair outcomes. It records zero public
answers, zero public traffic, zero production answer serving, and zero production pointer
mutation.

## Boundary

PA.5 authorizes internal shadow evidence only. It does not authorize public serving, canary
traffic, full production promotion, production pointer mutation, R2 writes, Qdrant writes,
Source mutation, Foundation mutation, release mutation, or secret persistence.
