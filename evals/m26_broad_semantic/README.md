# M26 R2O Broad Semantic Qualification Bank

Evaluation-only frozen bank for the next immutable broad semantic canary.

This directory does not contain runtime authority. Cases are derived from local
accepted canonical corpus artifacts under `pilot/m24/canonical-release/artifacts`
and are used only for static QA, captured-result auditing, and deterministic
next-run selection.

The bank intentionally includes answer, partial, abstain, clarification,
negative-control, graph, provenance, temporal, paraphrase, and sentinel cases.
The deterministic harness must not call an LLM and must flag semantic judgments
that require hostile reviewer inspection as `HOSTILE_SEMANTIC_REVIEW_REQUIRED`.
