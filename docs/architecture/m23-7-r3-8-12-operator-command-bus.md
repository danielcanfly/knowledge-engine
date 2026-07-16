# M23.7-R3.8.12 governed operator command bus

## Incident

GitHub Actions run `29521901629` passed exact-head validation, pinned Wrangler validation and the destructive deletion step. The script then failed before writing the deletion receipt, so artifact upload found no files and the governed final result failed.

The destructive run must not be rerun. The only lawful recovery is a read-only control-plane probe of the exact Worker:

```text
knowledge-engine-r3-8-29506217284
```

## Command bus

Issue `#565` is the locked operator command surface. A command executes only when all of these gates pass:

1. `issue_comment.created` on issue `#565`;
2. actor is `huaihsuanbusiness` with `OWNER` association;
3. `GITHUB_RUN_ATTEMPT=1`;
4. the comment body is one canonical single-line JSON command;
5. the body references a committed authorization path and a 256-bit nonce;
6. the authorization schema, digest, actor, issue and command type are exact;
7. the requested SHA equals the current accepted `main` head;
8. the exact command body occurs only once on the bus;
9. the command type is present in a static route allowlist.

The bridge accepts no arbitrary shell, workflow name, branch, URL or secret input.

## Initial static route

The first route is:

```text
r3_8_post_delete_recovery
```

It performs exactly two Cloudflare control-plane reads:

```text
GET /workers/scripts/<worker>/versions
GET /workers/scripts/<worker>/deployments
```

It does not invoke Wrangler deletion, deployment, Worker secrets, the Worker route, Qdrant or R2. It writes a privacy-safe receipt whether the result is absent, present, inconsistent or indeterminate.

Committed authorization digest:

```text
b2b247181bbdd276ef4cd393e9b91655a0460b764a89d9a7c9c8a8408a5ee357
```

Contract digest:

```text
9d3e7392a8bb6a65fa5f1fa66f225ee0a9414a78cc1896c99d867ddfd53914c6
```

## Operational effect

After implementation and independent reconciliation, ChatGPT can trigger an authorized route by posting the exact command to issue `#565` through the GitHub connector. The user no longer needs to manually copy `expected_head`, authorization paths or confirmation phrases into the Actions UI.

Every new operator capability still requires an explicit static route and committed authorization. The bus is a narrow drawbridge, not a universal remote.

## Preserved boundaries

- production retrieval remains lexical;
- `blocked_pending_retrieval_quality` remains active;
- `blocked_pending_latency` remains active;
- no Qdrant or R2 access is authorized;
- no blocker clearance, promotion, parent closure or M23.7 closure is authorized.
