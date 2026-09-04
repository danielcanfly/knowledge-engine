# M26 Console Gate A Repair-A Contract Index

This branch records the bounded Repair-A cross-lane contract convergence. It does not implement P01-P12 pages, regenerate the SM-00 client, change production, or mutate Cloudflare/R2/Qdrant/pointers.

## Canonical contract identity

```text
CANONICAL_OPENAPI_FILENAME=CANONICAL_ADMIN_API_OPENAPI.yaml
CANONICAL_OPENAPI_VERSION=1.1.0-gate-a-repair-a
CANONICAL_OPENAPI_SHA256=2e28c734404d4428450e0b8232d44314365cfb775a44b45803e9bf11be90743f
ONE_AUTHORITATIVE_OPENAPI=YES
```

The specification-compliant Repair-A RETURN ZIP is the frozen delivery container for the authoritative OpenAPI and its identity/mapping/validation artifacts. This repository index intentionally does not create a second OpenAPI copy.

## Convergence assertions

```text
READ_ENVELOPE_HAS_AVAILABILITY=YES
READ_ENVELOPE_HAS_PROVENANCE=YES
OBSERVED_AT_NULLABLE_WHEN_UNOBSERVED=YES
FRESHNESS_CAN_REPRESENT_STALE=YES
UNAVAILABLE_IS_DETERMINISTIC_AND_NON_FABRICATED=YES
QUALIFICATION_STATUS_SEPARATE_FROM_EFFECTIVE_STATE=YES
BLOCKED_AUTHORITY_NEVER_ENABLES_MUTATION=YES
QUALIFICATION_CANDIDATE_NEVER_ENABLES_MUTATION=YES
GENERIC_QA_0_100_SCORE_FILTER_ACTIVE=NO
SUGGESTED_QUESTIONS_85_RUBRIC_SCOPE=SuggestedQuestionsOnly
```

Current B03 status mapping frozen by Repair-A:

- `read_only` -> `read_only`, mutation unauthorized
- `unavailable` -> `unavailable`, mutation unauthorized
- `blocked_authority` -> `unavailable`, mutation unauthorized
- `qualification_candidate` -> `disabled`, mutation unauthorized

## Authority precedence

1. Gate A directives
2. SM-B01 transport/security/request/error/idempotency/audit semantics
3. SM-B02 shared read availability/provenance/observation/freshness semantics and generic-score prohibition
4. SM-B03 qualification evidence/status facts
5. Repair-A cross-lane status-to-effective-state mapping

Exact Repair-A success terminal:

```text
M26_CONSOLE_GATE_A_REPAIR_A_CONTRACT_CONVERGENCE_READY_FOR_SM00_REBIND
```
