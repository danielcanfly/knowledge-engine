# M25.4 Daniel Approval and Final Freeze

Daniel approved the exact M25.4 annotation candidate bound to PR #1047 candidate head
`cf56bad3b9128020214c3a30100ec741d6842e56`.

The approved authority record is GitHub issue comment `5053875354`. It approves:

1. annotation and adjudication policy digest
   `0e404be34a4dac4816dced3c9db1a0ec9543a83adcae83f01fe85f5a3d822246`;
2. all 30 provisional evidence-bound labels in suite digest
   `103db6e982e71ed8e4c442eb4f36f48b06eb846fdc3f339fb3cd078215b5ddfc`;
3. disputed-item count `0`.

The approval explicitly does not authorise M25.5.

## Candidate preservation

The approved candidate artifacts remain immutable:

- `m25-4-annotation-policy.json`
- `m25-4-gold-suite.provisional.json`
- `m25-4-baseline-report.provisional.json`
- `m25-4-daniel-annotation-gate.json`

The post-approval commit may only add finalisation records. It may not change the approved policy,
provisional suite, labels, expected outcomes, split assignments, evidence, rationale, baseline metrics,
resolver code, or thresholds.

## Final artifacts

- `m25-4-daniel-approval.json` stores the authority record.
- `m25-4-gold-suite.json` promotes the same 30 labels to `approved`.
- `m25-4-split-manifest.accepted.json` binds the final suite and item digests.
- `m25-4-adjudication-ledger.approved.json` records the Daniel decision.
- `m25-4-baseline-report.json` promotes the unchanged baseline metrics to `accepted_baseline`.

The final suite digest differs from the provisional digest only because approval statuses, suite
revision, and signed item/suite digests changed. Tests compare all semantic label content and reject
any drift.

## Authority boundary

This approval and finalisation do not authorise resolver calibration, M25.5, Source or Foundation
mutation, release or production-pointer mutation, R2 production or Qdrant mutation, serving changes,
or large-scale ingestion.
