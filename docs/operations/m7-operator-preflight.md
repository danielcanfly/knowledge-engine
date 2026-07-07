# M7 Operator Preflight

Status: `implemented`

Parent tracker: `#74`

Milestone tracker: `#79`

## Purpose

The operator preflight converts a governed batch spec into a deterministic readiness report and the next legal action. It performs no workflow dispatch and no Source, candidate, R2, GitHub, or production mutation.

## Command

```bash
python -m knowledge_engine.batch_cli preflight \
  --spec-path governed_batches/<batch-id>.json \
  --registry-path governed_batches/registry.json \
  --require-env SOURCE_READ_TOKEN \
  --require-env R2_ACCESS_KEY_ID \
  --require-env R2_SECRET_ACCESS_KEY \
  --require-env R2_BUCKET \
  --require-env R2_ENDPOINT_URL \
  --output evidence/operator-preflight.json
```

Run the command from the repository root with a clean worktree. `--allow-dirty` exists for isolated development tests and must not be used as production evidence.

## Checks

- registry schema and collision rules
- selected batch is registered
- batch spec schema and lifecycle completeness
- clean Git worktree
- production workflow exists
- production workflow dispatch inputs are exactly `request_path`
- named environment variables are present without printing their values
- committed production request matches batch operation and candidate identity when configured
- optional production pointer evidence is valid JSON with release and manifest identity

## Output

The evidence file includes:

- status
- batch ID
- lifecycle state
- next legal action
- worktree state
- production workflow inputs
- names of required environment variables
- request identity validation result when applicable
- production pointer identity when supplied
- `mutations_performed: []`

## Lifecycle next actions

- `planned` → `open_source_review`
- `source_reviewed` → `run_source_validation`
- `source_validated` → `build_candidate`
- `candidate_built` → `run_runtime_acceptance`
- `runtime_accepted` → `commit_production_request_spec`
- `request_spec_committed` → `review_production_promotion`
- `production_promoted` → `run_idempotent_replay_and_close`
- `closed` → `start_next_batch`

## Boundary

The command prints what is legal next. It never performs that action. Human review and existing workflow gates remain authoritative.
