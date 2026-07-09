# M12.7 Final Release-Blocking Gate and Closure

Status: implementation candidate  
Issue: #169  
Depends on: #167, #168, and completed M12.1–M12.4 slices  
Engine baseline before M12.5–M12.7: `cfc782fa2123ecaa15648a4b976500ce35a7ed10`

## Purpose

M12.7 composes the final runtime-quality decision from three exact artifacts:

1. the M12.4 release-quality decision;
2. the M12.5 retrieval and citation metrics artifact;
3. the M12.6 answer-quality and performance metrics artifact.

It produces a machine-verifiable release-eligibility decision. Eligibility is evidence only. This slice does not create a candidate, release request, promotion, rollback, Source change, production pointer mutation, or permanent-ledger entry.

## Required checks

The final gate requires:

- exact and unique artifact identities;
- complete required-artifact coverage;
- exact release and manifest agreement;
- every input artifact passed, not stale, and not release-blocking;
- the M12 no-write governance boundary on every artifact;
- no audience broadening;
- zero raw-fallback rate;
- complete metric sections;
- successful M12.1–M12.6 regression matrix.

Any mismatch fails closed and sets `promotion_eligible: false`.

## Output sections

The final `m12closure_` artifact includes:

- `query_eval_summary`;
- `retrieval_quality`;
- `citation_quality`;
- `faithfulness_summary`;
- `performance_summary`;
- `boundary_eval`;
- `regression_matrix`;
- `closure_matrix`;
- exact release, Source, and production identities;
- reviewer identity, timestamp, and notes;
- explicit no-write governance.

## Determinism

The final policy, artifact references, metric sections, boundary result, regression matrix, and failure reasons form a stable-JSON identity. Exact replay returns the same `m12gate_` and `m12closure_` identities.

## Locked baseline

M12 closure reconciles against:

```text
canonical Source: 2126db2ed4d372d3d61464fe31a86fc0243a1f24
production release: 20260708T040116Z-69a9f445699a
production manifest: 2b2630cfe3e8a6e25a8f210d68c70f3b9a31b3b26f33c6e3e41b8cc1676fc0bb
production pointer: 38e12c8686ee4ccf2beae0f073dead41b78e8f4548fdf7a4b0d0e273353906b5
```

Permanent ledger #30 remains open. No entry is added because M12 performs no production promotion or rollback.
