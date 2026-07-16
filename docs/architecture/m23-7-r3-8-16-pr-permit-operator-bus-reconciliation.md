# M23.7-R3.8.16 independent PR permit operator-bus reconciliation

Implementation PR #586 accepted head `5d43e1523807d06d50743efa40117eb1f8132b7d` and merged as `8faaede87af9e8fde62c48ba52ee1219abb4aecb`.

Independent review confirms an exact twelve-file implementation scope. Four of those files are successor-aware historical regression gates. Their historical authorization, contract and runtime identities remain unchanged; only their recognition of the reviewed PR-permit successor surface changed.

## Reconciled lifecycle

The operator bus is a same-repository two-stage pull request:

1. The request-only head adds exactly one request and returns `request_validated`. No route executes.
2. After the request head's required workflows succeed, a second commit adds exactly one permit.
3. The permit head has one parent, and that parent must equal the validated request head.
4. The request commit may add only the request. The permit commit may add only the permit.
5. The permit binds exact request path and digest, base SHA, v5 authorization digest, fresh permit nonce and exact request-validation, global-CI and M18 run IDs.
6. Only `pull_request.synchronize` on `operator_permits/m23/**` can execute the static read-only recovery route.

Modification, deletion, rename, extra files, merge commits, parent drift and unbound validation run IDs fail closed.

## Direct observability

The permit event produces a pull-request-triggered Actions run. The connected assistant can directly enumerate the run by permit head SHA, inspect jobs and logs, and download the governed artifact. No browser workflow dispatch, copied run URL or issue-comment webhook is needed.

## Exact-head evidence

All implementation workflows succeeded on the accepted head:

- PR permit operator bus `29528140967`;
- R3.8.15 successor regression `29528140881`;
- R3.8.14 successor regression `29528140857`;
- R3.8.13 observability regression `29528140721`;
- R3.8.12 successor regression `29528140712`;
- global CI `29528140892`;
- M17 `29528140632`;
- M18 `29528140762`.

Authorization SHA-256:

```text
1bf974d98d04be370efa82a3440399f6bc54999c68b5801f908bfc4350ce273a
```

Contract SHA-256:

```text
bf3101592c43a9a20cc06e5c87e6e05213ae9fdf595ee8e3e3634723ce055aa0
```

Independent reconciliation SHA-256:

```text
241a9754de2856634300a4e3db1b4c01550446da24a5a59409140f784471b938
```

## Disposition

After this reconciliation merges, create a fresh request-only PR from the reconciliation merge SHA using the v5 authorization. Add the permit only after request-head validation succeeds. Inspect and reconcile the permit-head evidence before merging the request-plus-permit PR.

Production retrieval remains lexical. Both blockers remain active. No deletion, deployment, Qdrant/R2 access, blocker clearance, promotion or closure is authorized by this reconciliation.
