# M23.7-R3.8.15 exact-base request-only scope validation

## Incident

Request PR #579 passed the following gates:

- exact request head and base ancestry;
- canonical request schema and digest;
- exact expected base identity;
- committed authorization path;
- fresh 256-bit nonce;
- static read-only route authority.

It failed only at the request-only scope check. That check invoked `git diff` with the branch name from `GITHUB_BASE_REF`, while Actions had checked out the exact PR head in detached-HEAD mode. A local branch named `main` is not part of the exact-head contract.

The request was closed without merge. No main push, operator execution or Cloudflare access occurred.

## Repair

The scope gate now receives explicit immutable identities:

```text
BASE_SHA = github.event.pull_request.base.sha
HEAD_SHA = github.event.pull_request.head.sha
```

It validates both as lowercase 40-character Git object IDs, requires them to differ, proves the checked-out HEAD equals `HEAD_SHA`, proves `BASE_SHA` is an ancestor of `HEAD_SHA`, and calculates the changed paths using:

```text
git diff --name-only <BASE_SHA> <HEAD_SHA>
```

The result must contain exactly the request path emitted by the canonical request validator. No local branch name is consulted.

## Fresh authorization

The v3 request identity appeared in a closed PR and is not reused. A new v4 read-only authorization is committed:

```text
operator_authorizations/m23/r3-8/post-delete-recovery-29521901629-v4.json
```

Authorization SHA-256:

```text
1375bf49d53ce7b8cc63bfc83c2e409e8458e40bdde3bc22952e0750f96de8a8
```

Contract SHA-256:

```text
a3edc3cd607d3a71eea48db7bfcccf1a8f9c5f4500cd5abd06595f5f5786e032
```

## Preserved surfaces

This repair changes only the request PR validation workflow and adds the fresh authorization plus its evidence records. It does not change:

- the request schema or validator;
- the push-triggered execution workflow;
- the Cloudflare recovery implementation;
- the fixed telemetry writer;
- prior authorizations;
- production retrieval or either blocker.

After implementation and independent reconciliation, a new request must be generated against the then-current main SHA. The closed request PR #579 must not be reopened or merged.
