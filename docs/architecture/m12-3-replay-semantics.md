# M12.3 Replay Semantics

M12.3 replay is defined as re-running `evaluate_golden_query_baseline(...)` with the same baseline contract and the same suite report.

## Deterministic inputs

The check identity includes only stable input data:

- baseline contract identity;
- suite report ID;
- aggregate counts;
- failure reasons;
- missing required cases;
- unexpected failure reasons;
- audience broadening list.

## Excluded inputs

The identity excludes:

- wall-clock time;
- host-specific paths;
- environment variables;
- random values;
- hidden raw evidence;
- mutable reviewer state.

## Idempotency guarantee

For a fixed baseline and report, the returned dictionary is expected to be equal across repeated executions. This is covered by tests and supports later machine-verifiable closure evidence.
