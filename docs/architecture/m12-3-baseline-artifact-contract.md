# M12.3 Baseline Artifact Contract

The M12.3 artifact is a deterministic check payload produced by comparing one `GoldenQueryBaseline` contract to one M12.2 `gqreport_` suite report.

## Inputs

- `GoldenQueryBaseline`, including reviewer notes and approved audiences.
- One M12.2 `gqreport_` suite report generated through the ACL-aware Runtime API.

## Output

The output shape is:

```json
{
  "schema_version": "1.0",
  "baseline_contract_id": "gqbaseline_<sha256-prefix>",
  "baseline_check_id": "gqbaselinecheck_<sha256-prefix>",
  "baseline_id": "m12-3-reference-quality-baseline",
  "report_id": "gqreport_<sha256-prefix>",
  "passed": true,
  "release_blocking": false,
  "failure_reasons": [],
  "governance": {
    "canonical_source_write_permitted": false,
    "candidate_write_permitted": false,
    "release_write_permitted": false,
    "production_write_permitted": false,
    "permanent_ledger_append_permitted": false
  }
}
```

## Identity inputs

`gqbaselinecheck_` identity includes:

- baseline contract identity;
- report ID;
- failure reasons;
- aggregate report counts;
- missing required cases;
- unexpected failure reasons;
- audience broadening list.

The identity does not include wall-clock time, host state, random values, mutable reviewer state, or hidden raw evidence.

## Replay rule

Re-running the same baseline against the same report must produce byte-for-byte equal check data.
