# M12.3 Release-Blocking Reasons

M12.3 introduces stable release-blocking reasons for golden-query baseline drift.

## Reasons

- `suite_id_mismatch`: the report was not produced from the approved suite contract.
- `release_id_mismatch`: the report evaluated a different release than the baseline.
- `manifest_sha256_mismatch`: the report evaluated a different release manifest.
- `passed_count_regression`: the passed case count fell below the baseline floor.
- `failed_count_regression`: the failed case count exceeded the baseline ceiling.
- `release_blocking_count_regression`: the count of release-blocking case evaluations exceeded the baseline ceiling.
- `required_case_missing`: one or more baseline-required cases are absent from the report.
- `unexpected_failure_reason`: the suite report contains a failure reason not explicitly allowed by the baseline.
- `audience_broadening`: the suite report includes an audience outside the baseline-approved audience set.
- `unexpected_report_release_blocking`: the report is release-blocking when the baseline did not allow any failure reason.

## Semantics

All reasons are fail-closed. A single reason sets `passed=false` and `release_blocking=true` on the baseline check.
