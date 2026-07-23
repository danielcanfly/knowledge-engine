# M25.6 Human Review and Admission Product Surface

## Status

Implementation candidate status: `m25_6_awaiting_daniel_browser_acceptance`.

M25.6 consumes the exact accepted M25.5 identity-governance artifacts and provides a protected,
item-level review console. It does not write Canonical Source, create Source pull requests, mutate
production state, or authorize M25.7.

## Product surface

The authenticated review console exposes:

- a thirty-item batch dashboard with no bulk-approval action;
- a source reader showing exact snapshot, derivative, offset and excerpt-digest locators;
- candidate and existing-Source comparison;
- ranked identity targets and M25.5 explanation signals;
- a read-only graph neighbourhood;
- proposed aliases, relations and governed tags;
- a structured before/after diff;
- approve, map, edit, split, reject and defer actions;
- a visible immutable decision digest;
- a downloadable audit export.

Benchmark fixtures intentionally do not contain source excerpt bytes. The UI displays exact evidence
locators and explicitly states that excerpt text is unavailable. It never fabricates excerpt content.

## Authentication

The review page, JavaScript and all APIs require HTTP Basic authentication. Startup refuses weak or
missing credentials. The unauthenticated route returns `401` with a Basic challenge. Browser
acceptance uses a dedicated test identity and a test-only secret supplied through environment
variables, not committed artifacts.

A production deployment may replace HTTP Basic with Cloudflare Access or the existing JWT authority,
but must preserve the authenticated-route contract and reviewer identity binding.

## Decision integrity

Every decision binds:

- exact batch SHA-256;
- exact review-item state SHA-256;
- previous ledger head SHA-256;
- reviewer identity and role;
- candidate IDs;
- evidence identities;
- M25.5 policy and calibrated-report identities;
- action, rationale and required acknowledgements;
- mapping, edit or split payload where applicable;
- timezone-qualified decision timestamp.

Decisions are append-only files in a digest chain. `HEAD.json` is atomically replaced only after the
immutable record is written. A stale batch, item state or ledger head fails closed. A terminal item
cannot be decided twice. A deferred item may later receive a terminal decision while preserving the
original record.

## Completion and authority

`admission_ready` becomes true only when all thirty items have a terminal item-level decision and no
item remains pending or deferred. Even then:

- `source_write_permitted` remains false;
- `github_pr_creation_permitted` remains false;
- `m25_7_authorized` remains false.

M25.7 authority can only arise from accepted M25.6 closure and a later governed executor stage.

## Browser acceptance

The dedicated exact-head workflow runs six authenticated Chromium journeys covering all decision
actions. It captures before/after screenshots, decision digests and an audit export. The candidate
must then be reviewed by Daniel against the exact PR head and browser-evidence artifact.

M25.6 cannot close until Daniel explicitly accepts the protected browser journeys. CI success alone
is not browser acceptance.
