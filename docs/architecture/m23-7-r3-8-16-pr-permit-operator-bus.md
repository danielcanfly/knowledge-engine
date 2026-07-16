# M23.7-R3.8.16 two-stage PR permit operator bus

## Why this surface exists

The connected GitHub application can reliably create branches, commits and pull requests, and it can enumerate pull-request-triggered Actions runs, jobs, logs and artifacts. It does not expose native workflow dispatch. Connector-created issue comments and a merge-triggered push request both failed to produce accepted, observable operator evidence, so neither is treated as a valid execution surface.

The replacement is a two-stage same-repository pull request whose second commit is an immutable execution permit.

## Stage 1: request validation

A request branch first adds exactly one canonical JSON file under:

```text
operator_requests/m23/**
```

The request binds the exact base SHA, static route, committed authorization path, authorization nonce, fixed status issue and request digest. The request head must pass the exact-head request/permit validator plus the repository's applicable CI.

At this stage no route executes. The validator emits:

```text
stage=request_validated
```

## Stage 2: permit commit

Only after the request head's required workflows succeed may a second commit add one permit JSON under:

```text
operator_permits/m23/**
```

The permit binds:

- the validated request head SHA;
- request path and request digest;
- exact base SHA;
- authorization digest;
- a fresh 256-bit permit nonce;
- exact successful request-validation, global-CI and M18 run IDs;
- the static route `r3_8_post_delete_recovery`;
- deny-by-default execution authority.

The permit head must have exactly one parent, and that parent must equal the validated request head. The request head may add only the request; the permit commit may add only the permit. Modification, deletion, rename, extra files and merge commits fail closed.

## Observable execution

The execution workflow runs only on:

```text
pull_request.synchronize
```

when `operator_permits/m23/**` changes. The PR must be same-repository and owned by `huaihsuanbusiness`. Rerun attempts are rejected.

The exact permit head is checked out and independently revalidated before the route job becomes eligible. The connected assistant can then directly enumerate the PR-triggered run and inspect its jobs, logs and artifact without user copy and paste.

The route performs only:

```text
GET /workers/scripts/<worker>/versions
GET /workers/scripts/<worker>/deployments
```

The artifact is named with prefix:

```text
m23-7-r3-8-16-pr-permit-recovery-
```

The request-plus-permit PR remains open until governed evidence is validated and independently reconciled. Merge occurs only afterward.

## Fresh authorization

```text
operator_authorizations/m23/r3-8/post-delete-recovery-29521901629-v5.json
```

Authorization SHA-256:

```text
1bf974d98d04be370efa82a3440399f6bc54999c68b5801f908bfc4350ce273a
```

Contract SHA-256:

```text
bf3101592c43a9a20cc06e5c87e6e05213ae9fdf595ee8e3e3634723ce055aa0
```

## Preserved boundaries

Production retrieval remains lexical. Both blockers remain active. The permit bus grants no Worker deletion, deployment, secret mutation, arbitrary route, Qdrant/R2 access, pointer/source mutation, blocker clearance, promotion, parent closure or M23.7 closure.
