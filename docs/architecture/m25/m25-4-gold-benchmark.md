# M25.4 Concept Identity Gold Set and Benchmark Harness

## Entry contract

- Engine base: `744cfdc830da4a7bcfd4ed6ec3cf55972b042358`
- Required predecessor: `m25_3_extraction_worker_accepted`
- Existing resolver: `knowledge_engine.m21_entity_resolution`
- Resolver Source binding remains unchanged.
- Resolver thresholds and runtime code are not calibrated in this stage.

## Delivered surfaces

- provisional annotation policy and guide;
- 30 evidence-bound gold items across ten classes and three frozen splits;
- immutable split manifest and leakage checks;
- adjudication ledger with Daniel as final authority;
- deterministic benchmark runner and CLI;
- provisional baseline report;
- JSON schemas, contract tests, and exact-head CI;
- machine-readable Daniel approval package.

## Baseline result

The provisional baseline measures the existing resolver without changing it:

- semantic identity decision accuracy: **1.000000**;
- false identity merges: **0 / 30**;
- explanation-signal coverage: **0.600000**;
- explanation-signal gaps: **12 / 30**.

The gaps are concentrated in four classes:

- near-match distinction;
- parent/child distinction;
- explicit polysemy explanation;
- supersession distinction.

The current resolver is conservative on the provisional suite, but it does not emit the semantic
explanation signals required for these classes. M25.5 may use the accepted gold set to improve
explainability and calibration, but M25.4 itself does not make those changes.

## Safety and authority

All artifacts are candidate-only. The benchmark cannot write Source, Foundation, release, production
pointer, R2 production, Qdrant, review decisions, or serving configuration. Live providers and
credentials are not used. The final split is never used for calibration.

## Daniel gate

Implementation may be tested before approval, but the PR must not be merged and M25.4 must not be
accepted until Daniel explicitly approves:

1. the annotation/adjudication policy bound by its exact SHA-256;
2. all 30 provisional labels bound by the suite SHA-256;
3. the fact that the disputed-item count is zero.

Approval applies only to the exact PR head and digests presented.
