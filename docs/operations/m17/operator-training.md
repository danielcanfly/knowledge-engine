# M17 Operator Training and Qualification

Return to the [Operator Runbook Index](../README.md).

M17.5 turns the architecture canon, runbooks, failure atlas, and inspection tools into a repeatable
qualification program. Reading is necessary but insufficient. A candidate operator must complete all
seven exercises, submit bounded digest-bound evidence, demonstrate safe-stop judgment, and be assessed
by a different evaluator.

## Qualification outcome

A candidate is `qualified` only when all of the following are true:

- the weighted score is at least 85 out of 100;
- every critical exercise is passed;
- no exercise is blocked, unknown, omitted, duplicated, or above its maximum score;
- the evaluator identity differs from the operator identity;
- the attempt number is between 1 and 3;
- every exercise includes at least one SHA-256-bound evidence item;
- no exercise claims production authority or performs a real governed mutation.

Anything else is `not_qualified` or `blocked`. A training result is not approval to operate production.

## Seven required exercises

### 1. Architecture orientation

Explain the control, build, runtime, and feedback planes; identify canonical Source, derived artifacts,
production pointers, evidence stores, and trust boundaries; and name the universal stop conditions.

### 2. Planned governed batch

Create a non-executing batch plan that records exact identity placeholders, authority boundaries,
evidence handoffs, rollback readiness, ACL scope, and stage-by-stage stop conditions.

### 3. Source package review

Review a prepared Source package fixture. Detect unsupported claims, unresolved contradiction,
provenance gaps, audience ambiguity, and any attempt to treat generated artifacts as editable truth.

### 4. Candidate evidence inspection

Use local or read-only evidence to verify candidate identity, manifest digest, runtime evaluation,
citation quality, ACL-negative behavior, and acceptance completeness. Missing evidence must block.

### 5. Non-production dry run

Execute the lifecycle only against an isolated fixture or temporary filesystem store. The exercise may
create local disposable artifacts but must not contact or mutate production, Source, permanent ledger,
credentials, approvals, pointers, caches, or R2 objects.

### 6. Rollback drill

Given a simulated failed or uncertain promotion, classify the state, preserve evidence, identify the
required authority, select the governed recovery path, and verify the expected post-rollback query,
citation, cache, pointer, and ACL checks without performing a real rollback.

### 7. Closeout package

Assemble a bounded local closeout package containing exact identities, verification results, evidence
digests, unresolved items, and a clear resume-or-stop decision. A closeout package is evidence, not a
ledger append or lifecycle mutation.

## Assessment file

`knowledge-qualify assess` accepts a local JSON file with pseudonymous operator and evaluator IDs,
attempt number, and one result for every exercise. Each result contains status, awarded score, and
one or more named SHA-256 evidence items. Raw private text, secret material, raw queries or answers,
private object locations, network endpoint metadata, and unbounded traces are forbidden.

Example shape:

```json
{
  "operator_id": "operator-17",
  "evaluator_id": "evaluator-04",
  "attempt": 1,
  "results": [
    {
      "exercise_id": "architecture_orientation",
      "status": "passed",
      "score": 10,
      "evidence": [{"name": "orientation-report", "sha256": "<64 hex>"}]
    }
  ]
}
```

## Commands

```bash
knowledge-qualify plan
knowledge-qualify assess --submission qualification-submission.json
```

Both commands emit canonical JSON with a SHA-256 report identity. They use local files only and expose
no remote mutation surface.

## Governance

- Training uses `read_only`, `local_output`, or `isolated_fixture` authority only.
- The evaluator may request a new attempt but may not change exercise weights or criticality.
- Evidence may be regenerated only through a new numbered attempt.
- Three failed or blocked attempts require retraining before a new qualification cycle.
- Self-assessment is invalid.
- A passing report expires when the curriculum schema or referenced operational contracts change.
- Qualification does not replace explicit approval for any governed operation.

## Acceptance

Run:

```bash
python scripts/m17_operator_qualification_acceptance.py \
  --root . \
  --registry docs/operations/m17/training-registry.json \
  --output .artifacts/m17/operator-qualification-acceptance.json
```

The acceptance report validates curriculum coverage, weights, critical exercises, exact references,
authority boundaries, privacy rules, assessment logic, and report tamper detection.
