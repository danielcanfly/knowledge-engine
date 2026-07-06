# M6-001 Source Validation Evidence

Status: `source validation passed / candidate planning required`

Parent tracker: `#42`

Child slice: `#57`

Batch spec: `docs/batches/m6-001-llm-wiki-foundation-batch.md`

Reviewed Source repository: `danielcanfly/knowledge-source`

Reviewed Source SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`

## 1. Validation workflow

Workflow file reviewed:

- `.github/workflows/validate.yml`
- Workflow name: `Validate Knowledge Source`
- Trigger: pull request and push to `main`
- Job: `validate-and-preview`

The workflow runs the following validation gates:

- Python setup and dependency installation
- `ruff check scripts tests`
- `pytest`
- `scripts/validate_source.py`
- `scripts/validate_delivery_contract.py`
- pinned Knowledge Engine Builder install
- deterministic preview build twice
- preview output diff check
- validation and preview evidence upload

## 2. Run evidence

Source validation run:

- Repository: `danielcanfly/knowledge-source`
- Run ID: `28771739838`
- Job ID: `85306679196`
- Job name: `validate-and-preview`
- Job conclusion: `success`
- Source SHA validated by artifact name: `6a35f9f35e4c6c599a266710344f760c399d914d`

Completed successful steps:

- Set up job
- checkout
- setup-python
- install validation dependencies
- run source quality gates
- install pinned Knowledge Engine Builder
- build deterministic preview twice
- collect validation and preview evidence
- upload validation and preview evidence
- complete job

## 3. Artifact evidence

Validation artifact:

- Artifact ID: `8101046344`
- Artifact name: `knowledge-source-validation-6a35f9f35e4c6c599a266710344f760c399d914d`
- Artifact digest: `sha256:d8012852c831df3b16ef46ea2b0849783dfb169ce9c3e3f0862e0f222114acfa`
- Artifact size: `7107`
- Artifact expired: `false`
- Artifact created at: `2026-07-06T06:15:01Z`
- Artifact expires at: `2026-08-05T06:15:00Z`
- Artifact workflow run ID: `28771739838`
- Artifact head branch: `main`
- Artifact head SHA: `6a35f9f35e4c6c599a266710344f760c399d914d`

The workflow is configured to upload evidence files including:

- `source-quality.log`
- `source-validation.json`
- `delivery-contract-validation.json`
- `preview-a-result.json`
- `preview-b-result.json`
- `preview-manifest.json`
- `source-snapshot.json`

## 4. Candidate gate decision

This evidence satisfies the M6.8 requirement for Source validation success at reviewed Source SHA.

The candidate build remains blocked until the next planning step records:

- final public acceptance query strings
- final citation target mapping
- final boundary query string
- Builder / Foundation rotation decision

## 5. Non-authorization

This evidence does not authorize production promotion. It only records Source validation success and prepares the batch for candidate planning.
