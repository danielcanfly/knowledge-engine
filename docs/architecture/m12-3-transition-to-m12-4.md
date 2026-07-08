# M12.3 to M12.4 Transition

M12.3 provides the first immutable quality baseline check for Runtime query evaluation.

M12.4 should build on this by expanding provider/runtime evaluation coverage without weakening:

- deterministic identities;
- ACL-filtered evaluation;
- immutable evidence;
- replay/idempotency;
- fail-closed release-blocking reasons;
- no direct canonical Source or production mutation.

M12.4 should treat `gqbaselinecheck_` as an available evidence input, not as a production approval.
