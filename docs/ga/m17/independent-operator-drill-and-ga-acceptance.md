# M17.7 Independent Operator Drill and GA Acceptance

Return to the [v1 GA evidence index](../README.md).

M17.7 is the final Knowledge OS v1 gate. A clean-room operator job receives repository files only,
produces a deterministic drill transcript, and dispatches no real governed mutation. A separate
evaluator job consumes that transcript, revalidates the M17.6 evidence matrix, and may emit
`ga_accepted` only when every required check passes.

## Independence model

The drill requires:

- an operator identity distinct from the evaluator identity;
- `repository_only` context;
- exactly the four canonical entry pages listed in
  `independent-ga-contract.json`;
- no chat history, hidden hints, copied private notes, or undocumented procedures;
- runtime-supplied Engine, Source, release, manifest, and pointer identities;
- digest-bound evidence for every stage, capability, and safe-stop decision.

The workflow separates the operator and evaluator into different jobs. The operator artifact is
uploaded and then downloaded by the evaluator. The evaluator does not regenerate or edit the
transcript.

## Complete lifecycle drill

The operator must cover all 18 ordered phases from the M17.2 registry:

1. preflight
2. intake
3. synthesis preparation
4. synthesis validation
5. resolution
6. human review
7. Source package
8. Source PR boundary
9. Source validation
10. candidate build boundary
11. candidate acceptance
12. promotion request
13. production approval boundary
14. production promotion boundary
15. runtime verification
16. permanent-ledger boundary
17. batch closeout boundary
18. final reconciliation

Read-only and local stages are verified from repository contracts. Every governed external mutation
stage is represented through `isolated_boundary_simulation`, with `mutation_dispatched=false`.
The drill proves that the operator understands the authority boundary; it does not grant or exercise
that authority.

## GA capability coverage

The transcript contains one passed, SHA-256-bound record for each GA-01 through GA-20 capability.
The evaluator independently reruns the M17.6 evidence validator. A missing row, evidence gap, broken
reference, or changed registry blocks GA.

## Safe-stop qualification

The operator must stop correctly in four mandatory scenarios:

- missing approval;
- stale expected-previous identity;
- ACL broadening;
- replay conflict.

Each scenario must end in `stopped_safely`. Continuing after any of these conditions blocks GA.

## Commands

Generate an isolated operator transcript:

```bash
knowledge-ga drill \
  --root . \
  --engine-sha <ENGINE_SHA> \
  --source-sha <SOURCE_SHA> \
  --release-id <RELEASE_ID> \
  --manifest-sha256 <MANIFEST_SHA256> \
  --pointer-sha256 <POINTER_SHA256> \
  --operator-id <OPERATOR_ID> \
  --output independent-operator-transcript.json
```

Evaluate it with a different identity:

```bash
knowledge-ga assess \
  --root . \
  --transcript independent-operator-transcript.json \
  --evaluator-id <EVALUATOR_ID> \
  --output ga-acceptance-report.json
```

The final report is canonical JSON with a SHA-256 identity. A successful report contains:

```json
{
  "status": "ga_accepted",
  "ga_accepted": true,
  "stage_count": 18,
  "capability_count": 20,
  "safe_stop_count": 4
}
```

## Meaning of GA acceptance

`ga_accepted` means the repository contains complete implementation evidence and a clean-room
operator can reconstruct the documented lifecycle, respect every authority boundary, identify hard
stop conditions, and reconcile all required identities without undocumented help.

It does not create approval for a future production operation. Every later Source change, candidate
publication, production promotion, ledger append, rollback, or closeout still requires its own exact
governed authority.

## Closure

After the accepted head passes all selected workflows and is guarded-merged:

- close M17.7 as completed;
- close M17 parent issue #234 as completed;
- keep permanent production ledger #30 open and unchanged;
- record the final Engine merge identity in the M17 closure comment;
- retain the workflow transcript and GA acceptance report as immutable CI artifacts.
