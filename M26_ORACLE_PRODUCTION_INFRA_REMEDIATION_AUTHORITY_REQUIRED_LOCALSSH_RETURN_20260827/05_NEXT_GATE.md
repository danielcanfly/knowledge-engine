# Next Gate

NEXT_GATE=HPM_PRODUCTION_INFRA_REMEDIATION_AUTHORITY

Codex must not resume Repair2 construction in the current state.

The next safe sequence is:

1. HPM grants or denies narrowly scoped Oracle production-infra remediation authority.
2. If granted, perform only the approved remediation with pre/post evidence.
3. Recollect host and Docker health matrix.
4. Resume Repair2 candidate construction only if Docker daemon/API health is safe and production state is readable without mutation.

Target terminal after successful future repair construction:

M26_REPAIR2_CODEX_RECOVERY_CANDIDATE_READY_FOR_FRESH_AUDIT

Current terminal:

M26_ORACLE_PRODUCTION_INFRA_REMEDIATION_AUTHORITY_REQUIRED

