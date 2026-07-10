# M15.7 Alerts, Daily Report, Acceptance, and Closure

M15.7 adds the final read-only acceptance layer for M15. It assembles the six prior M15 evidence surfaces into a deterministic daily report and evaluates whether the M15 parent milestone can be closed.

## Inputs

The report requires one fresh artifact for each section:

1. observability contracts
2. runtime telemetry
3. release health
4. governance health
5. freshness impact
6. feedback triage

Every artifact must carry the same Engine SHA, canonical Source SHA, release ID, manifest SHA-256, and production pointer SHA-256.

## Alert behavior

Alerts are closed and deterministic:

- missing evidence is critical;
- identity drift is critical;
- unhealthy evidence is critical;
- unknown evidence is warning;
- stale evidence is warning.

The alert list is sorted by severity, section, and reason. The daily report is canonical JSON with a SHA-256 artifact identity.

## Closure gates

The report emits gates for privacy, identity, evidence completeness, health, freshness, feedback, and no-write authority. Closure is `ready_to_close` only when all gates pass.

## Privacy and authority boundaries

M15.7 rejects raw query text, raw answer text, tokens, authorization headers, cookies, JWT material, private excerpts, raw IP or hostname material, private URI schemes, arbitrary tracebacks, and extra evidence fields.

M15.7 has no authority to mutate Source, create a Source PR, dispatch correction candidates, write production, repair pointers, purge cache, mutate R2, roll back releases, physically delete objects, or append the permanent ledger. It is an acceptance switchboard, not a production actuator.
