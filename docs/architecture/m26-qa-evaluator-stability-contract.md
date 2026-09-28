# M26 QA evaluator stability contract

The semantic evaluator is an external model and its raw rubric total is an observation, not an independently reproducible release decision.

The server owns the decision contract:

- nominal Answer Quality threshold: 85;
- provider-only scores 83 through 87 are the explicit uncertainty band;
- when no stronger runtime-owned hard failure exists, every score in that band is classified identically as BORDERLINE_SEMANTIC_SCORE;
- the top-level QA result remains fail, consistent with the existing Pass/Fail/Pending/Error product contract;
- 88 is the first clear-pass score when no hard failure exists;
- scores below 83 are clear-fail scores;
- runtime-owned grounding, citation, provider/runtime and abstention failures always take precedence over the boundary policy.

aq-decision-policy/v1 is emitted with evaluator payloads together with the raw score band and clear-pass boundary. This keeps the raw provider score available for observability without letting an 83/87 model fluctuation flip the product verdict or failure-family identity.

Identical semantic inputs are fingerprint-cached by evaluator version/provider/model, so repeated reads reuse the canonical first evaluation rather than silently resampling the provider.

This policy does not lower the Answer Quality threshold, relax grounding, or convert borderline answers into PASS.
