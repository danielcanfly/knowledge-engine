# M26.PA.6 Canary, SLO, and Rollback

Status: `m26_pa_6_canary_slo_rollback_accepted`

M26.PA.6 proves bounded canary governance before any production-promotion decision. It
requires an allowlisted audience, allowlisted route, SLO enforcement, error budget, kill
switch, automatic stop conditions, rollback plan, and rollback drill. Full production
promotion remains forbidden.

## Evidence

- Policy: `pilot/m26/m26-pa-6-canary-policy.json`
- Cases: `pilot/m26/m26-pa-6-benchmark-cases.json`
- Entry contract: `pilot/m26/m26-pa-6-entry-contract.json`
- Contract registry: `pilot/m26/m26-pa-6-contract-registry.json`
- Acceptance: `pilot/m26/m26-pa-6-acceptance.json`
- Implementation: `src/knowledge_engine/m26_canary_slo_rollback.py`

The accepted benchmark contains 12 cases: ready canary records, SLO stops, rollback hold,
and authority-escalation attempts. Attempted traffic and authorized traffic are reported
separately, so rejected escalation cases cannot inflate the authorized canary exposure.

## Boundary

PA.6 authorizes bounded canary evidence only. It records zero full-production traffic, zero
production pointer mutation, and zero protected Source, Foundation, or release mutation.
The next stage, M26.PA.7, must make the Daniel final decision and final reconciliation.
