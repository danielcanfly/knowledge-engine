# M23.7-R3.8.13 operator command self-reporting telemetry

## Problem

The governed operator command bus removes manual browser dispatch, but the connected GitHub app does not list arbitrary `issue_comment` workflow runs. Without a bounded writeback, the operator would still need to copy the run URL back into chat.

The first command comment is `4995226881`. It is intentionally single-use and must never be reposted.

## Telemetry channel

The command bus retains its only trigger prefix:

```text
M23_OPERATOR_COMMAND 
```

Status comments use a separate non-triggering prefix:

```text
M23_OPERATOR_STATUS 
```

The workflow posts two canonical status records to locked issue #565:

1. `accepted`, after exact command, nonce, authorization and sole-occurrence validation;
2. `final`, after the routed job has produced and uploaded governed evidence.

Each record binds the exact Actions run ID, run URL, command type, expected head and authorization digest. The final record also binds the governed exit code and artifact name.

## Write boundary

The workflow permission changes only from `issues: read` to `issues: write`. The status writer has a fixed repository and fixed issue number. It accepts no issue number, repository, API URL or arbitrary message body from the command.

Status records cannot trigger an operator route because:

- their prefix differs from `M23_OPERATOR_COMMAND`;
- their author is the GitHub Actions identity, not `huaihsuanbusiness`;
- the route still requires `OWNER` association and exact canonical command authorization.

## Fresh authorization

A new one-time authorization is committed for the same read-only recovery route:

```text
operator_authorizations/m23/r3-8/post-delete-recovery-29521901629-v2.json
```

Authorization SHA-256:

```text
bd3b54dae6566aac70f521ac3ff3bedb7d3d2fa7b9ed915c8659ecb603e62496
```

Contract SHA-256:

```text
39849c636a825aacc55656db5b7c6359eeb89a5a7db0b386859942650e043149
```

## Preserved boundaries

The route remains read-only Cloudflare control-plane recovery. It performs no Worker deletion, deployment, secret mutation, route invocation, Qdrant/R2 access, blocker clearance, promotion or closure.

Production retrieval remains lexical. Both blockers remain active.
