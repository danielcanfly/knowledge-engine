# M24.12 Authenticated Live URL Binding

P9 reran the P8 live URL lifecycle after Daniel added a Cloudflare token with
Pages, Access, and DNS authority.

## Outcome

The live URL is now Access-protected.

- Pages project `llm-wiki-m24-internal` exists.
- The P6 internal product package was deployed to production by Pages Direct
  Upload.
- A Pages advanced-mode `_worker.js` defense-in-depth guard was added for the
  default Pages host family.
- Cloudflare Access self-hosted applications protect the custom hostname, the
  primary Pages host, and the Pages preview host pattern.
- Each Access application has one single-operator allow policy.
- `m24-internal.danielcanfly.com` has one proxied CNAME targeting the Pages
  host family.

Bounded unauthenticated observation reached Cloudflare Access for all three host
classes:

- custom hostname;
- primary Pages host;
- Pages preview host.

No unauthenticated observation saw the M24 release content.

## Remaining Acceptance

P9 is pending Daniel manual browser acceptance only:

1. open `https://m24-internal.danielcanfly.com/`;
2. complete Cloudflare Access authentication;
3. verify the canonical M24 internal product release renders;
4. record acceptance in the follow-up acceptance issue or PR.

The Pages custom-domain API still reports the custom hostname as `pending`.
External HTTPS observation already reaches Cloudflare Access, so this is tracked
as domain activation telemetry rather than a public exposure blocker.

## Evidence Hygiene

The committed P9 evidence intentionally excludes:

- Cloudflare token values;
- operator email values;
- raw headers;
- raw response bodies;
- raw API error bodies;
- preview full URLs;
- Access application ids and audience tags.

The evidence records only bounded state such as host class, HTTP status class,
Access-wall observation, policy count, CNAME count, and custom-domain status.

## Boundary

P9 does not authorize production semantic or hybrid retrieval, semantic serving,
production answer serving, Source mutation, production pointer mutation, R2
mutation, Qdrant mutation, credential mutation, traffic mutation, or permanent
ledger mutation.

Production retrieval remains lexical. Semantic promotion remains a separate M24
decision gate before any production semantic or hybrid retrieval work.
