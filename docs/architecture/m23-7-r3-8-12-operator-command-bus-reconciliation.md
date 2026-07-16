# M23.7-R3.8.12 independent operator command bus reconciliation

## Reconciled implementation

Implementation PR #567 accepted head `c912aa51cdc9bb030c9f42a0de340dc067583078` and merged as `75065a0d278fb0a82ffc9852f8af7cd2e268a3ac`.

The implementation introduced exactly nine files. Existing remote observation, deletion, recovery, Worker runtime, latency thresholds and schema-v2 deletion authorization were not changed.

## Independent findings

The operator command bus is bound to locked issue #565 and accepts only `issue_comment.created` events from `huaihsuanbusiness` with `OWNER` association.

Every command must provide canonical single-line JSON containing:

- an exact current `main` SHA;
- a repository-bounded committed authorization path;
- a 256-bit nonce.

The validator independently checks the authorization schema, digest, actor, issue number, command type, Worker identity and deny-by-default authority. The workflow also proves the exact comment body occurs only once, and rejects rerun attempts.

The route registry is static. The first and only route is:

```text
r3_8_post_delete_recovery
```

No arbitrary workflow name, branch, URL or shell is accepted.

## Recovery boundary

The recovery implementation performs only:

```text
GET /workers/scripts/<worker>/versions
GET /workers/scripts/<worker>/deployments
```

It contains no Worker delete, deploy, secret mutation, route invocation, Qdrant access or R2 access. It always writes privacy-safe success or failure evidence and never replays deletion run `29521901629`.

## Exact-head evidence

All implementation workflows succeeded on the accepted head:

- operator command bus gate: `29523118777`;
- global CI: `29523118721`;
- M17 Architecture Canon Acceptance: `29523118785`;
- M18 Graph v2 acceptance: `29523118645`.

Authorization SHA-256:

```text
b2b247181bbdd276ef4cd393e9b91655a0460b764a89d9a7c9c8a8408a5ee357
```

Contract SHA-256:

```text
9d3e7392a8bb6a65fa5f1fa66f225ee0a9414a78cc1896c99d867ddfd53914c6
```

Reconciliation SHA-256:

```text
f13f527b479f8691aec3f8dfd0bc7b06723298fe6acbf51d727cea45e87cbd37
```

## Disposition

After this reconciliation merges, the exact one-time command may be posted by ChatGPT through the GitHub connector to issue #565, using the reconciliation merge SHA. No browser workflow dispatch is required.

Production retrieval remains lexical. Both blockers remain active. No blocker clearance, #520/#474 closure, promotion or M23.7 closure is authorized.
