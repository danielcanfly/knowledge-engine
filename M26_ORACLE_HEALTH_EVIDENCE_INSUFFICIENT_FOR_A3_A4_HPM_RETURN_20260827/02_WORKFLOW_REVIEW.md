# Workflow Review

Reviewed workflow:

`.github/workflows/m26-e5-repair2-actual-construction.yml`

Observed failed step:

`Start repaired Oracle and prove no-shim load`

The workflow created a run-scoped candidate name:

`m26-e5-r2-oracle-isolated-m26blog-59012fe-520aed-run-33048885469`

The run log shows:

- SSH keyscan was nonfatal.
- SCP succeeded.
- Remote unpack succeeded.
- Production base inspect eventually passed.
- Candidate cleanup step began.
- Storage target discovery eventually passed.
- `docker create` began.
- `docker create --name m26-e5-r2-oracle-isolated-m26blog-59012fe-520aed-run-33048885469` timed out at 300s.

The local diagnosis workflow added for evidence collection is:

`attached/m26-oracle-production-health-evidence-audit.yml`

Important correction applied:

The diagnosis workflow no longer claims pure read-only while unconditionally running a Docker create latency probe. The nonproduction Docker create latency probe is disabled by default behind:

ALLOW_NONPROD_DOCKER_CREATE_PROBE=0
DIAGNOSTIC_DOCKER_CREATE_MUTATIONS=0

When the flag is not enabled, the workflow records:

DOCKER_CREATE_LATENCY=NOT_COLLECTED_NONPROD_CREATE_PROBE_NOT_AUTHORIZED

The workflow was not pushed and was not triggered.

