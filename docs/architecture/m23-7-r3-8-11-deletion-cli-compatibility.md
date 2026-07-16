# M23.7-R3.8.11 Wrangler deletion CLI compatibility repair

## Disposition

GitHub Actions run `29517518128` did not delete the authorized diagnostic Worker. The job failed in the pre-deletion Wrangler surface check because `wrangler@4.111.0 delete` accepts the Worker name as positional `[name]`, while the workflow and executor incorrectly required `--name`.

The deletion step was skipped and no evidence directory or deletion receipt was created. The exact Worker remains governed by the existing schema-v2 authorization:

```text
knowledge-engine-r3-8-29506217284
```

## Repair

The repaired command is constructed by a pure bounded function:

```text
npx --yes wrangler@4.111.0 delete <worker_name> --config <generated_config> --force
```

The Worker name remains constrained by the existing run-ID-derived regular expression. `--name` is forbidden on the delete path. The post-delete absence proof continues to use `wrangler versions list --name <worker_name>`, where `--name` is a valid option for that distinct command.

Both the manual deletion workflow and pull-request CI now validate the exact pinned help surface:

- `wrangler delete [name]` must be present;
- `--force` must be present;
- `--name` must be absent from delete help.

Adversarial tests verify the exact argument vector, reject malformed Worker identities, exercise the deletion and control-plane absence calls, and require a privacy-safe receipt only after absence is proven.

## Historical regression compatibility

Two historical workflows also required correction. Their original gates compared every later pull request against the exact file set of their own implementation PR. That converted a useful regression into a permanent freeze and rejected this bounded repair even though the accepted identity contracts and runtime were unchanged.

The R3.8.8 and R3.8.10 gates now preserve:

- their deterministic contract digests;
- recovery and full identity semantics;
- observation, recovery and Worker runtime ancestry;
- schema-v2 authorization validation and the exact four-version/four-deployment identity set;
- read-only and lexical-production boundaries.

They no longer require all future changes to match a stale historical file list, and the artifact-recovery workflow no longer treats the separately governed deletion workflow as immutable implementation content.

## Preserved identities and authority

This repair does not change:

- the schema-v2 deletion authorization;
- the four reconciled Worker version IDs;
- the four reconciled Worker deployment IDs;
- the recovery receipt, evidence seal or independent reconciliation identities;
- the observation runtime, Worker runtime, candidate collection or thresholds;
- production retrieval, which remains lexical;
- either blocker, both of which remain active.

This implementation does not authorize a workflow dispatch or deletion. After exact-head CI, expected-head merge and independent reconciliation, a fresh first-attempt manual deletion workflow may be dispatched against the then-current main SHA and the existing committed authorization path. Run `29517518128` must not be rerun.

## Next gate

```text
implementation exact-head CI
→ expected-head merge
→ independent reconciliation
→ fresh one-time deletion dispatch
→ deletion receipt validation and seal
→ deletion independent reconciliation
```

No blocker clearance, R3 final reconciliation, parent `#474` closure or M23.7 closure is authorized by this repair.
