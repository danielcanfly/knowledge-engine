# M12.4 Release Quality Gate

M12.4 bundles M12 runtime-quality evidence into one deterministic, replayable, fail-closed release-quality decision artifact.

The gate consumes explicit immutable artifact references from:

- M12.1 `qeval_` runtime query evaluations;
- M12.2 `gqreport_` golden query suite reports;
- M12.3 `gqbaselinecheck_` baseline checks.

It emits:

- `rqgate_`: the immutable policy identity;
- `rqdecision_`: the deterministic gate decision identity.

## Inputs

`ReleaseQualityGatePolicy` requires:

- exact release ID;
- exact release manifest SHA-256;
- exact canonical Source SHA;
- exact production release, manifest, and pointer baselines;
- reviewer identity;
- exact review timestamp;
- non-empty notes;
- required immutable artifact IDs;
- approved audiences.

## Fail-closed behavior

The gate blocks when any artifact is:

- missing;
- duplicated;
- missing an identity;
- failed;
- release-blocking;
- stale;
- from a mismatched release or manifest;
- carrying an audience outside the approved audience set.

The gate preserves artifact references only. It does not inline hidden raw evidence, broaden ACL, or re-run retrieval.

## No-mutation boundary

Every decision includes:

```json
{
  "canonical_source_write_permitted": false,
  "source_pr_creation_permitted": false,
  "candidate_write_permitted": false,
  "release_write_permitted": false,
  "production_write_permitted": false,
  "rollback_permitted": false,
  "permanent_ledger_append_permitted": false
}
```

M12.4 is evidence for downstream gating, not an approval surface and not a production mutation path.
