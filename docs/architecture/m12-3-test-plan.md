# M12.3 Test Plan

## Unit and integration coverage

`tests/test_golden_query_baseline.py` covers:

1. Successful baseline check over an M12.2 suite report.
2. Replay/idempotency: identical baseline and report produce identical check payloads.
3. Quality regression: lower passed count and higher failed count fail closed.
4. Unexpected failure reasons fail closed.
5. Suite identity drift fails closed.
6. Manifest drift fails closed.
7. Audience broadening fails closed.
8. Incomplete baseline contracts fail closed at construction time.
9. Governance flags deny canonical Source, candidate, release, production, and permanent ledger writes.

## Existing coverage reused

M12.3 deliberately reuses the M12.2 suite runner in tests so the baseline check is exercised against real Runtime query responses and real `evaluation` evidence, rather than synthetic-only payloads.

## Expected gates

- Ruff.
- Pytest.
- Python compileall.
- CI workflow.
- R2 Canary.
- R2 Release Integration.

## Acceptance

The branch may merge only after exact-head CI, R2 Canary, and R2 Release Integration are all successful.
