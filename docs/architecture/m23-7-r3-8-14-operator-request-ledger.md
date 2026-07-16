# M23.7-R3.8.14 merge-triggered operator request ledger

## Disposition

The connected GitHub app can create owner comments, but the two governed comments `4995226881` and `4995349400` did not produce accepted operator status. Comment creation is therefore retained only as historical evidence and is not an execution surface.

## Request ledger

Operator execution is triggered by an immutable request file merged to `main` under:

```text
operator_requests/m23/**
```

The workflow runs on the resulting `push`. It rejects rerun attempts and requires:

- `refs/heads/main`;
- exact event `before` and `after` SHAs;
- exactly one newly added request JSON;
- no modified, deleted or renamed request;
- canonical one-line JSON plus newline;
- a request ID matching its filename;
- the exact pre-merge base SHA;
- a committed authorization path and matching 256-bit nonce;
- the fixed status issue #565;
- a statically allowed command type.

The event `after` SHA becomes the exact execution head. A request PR is therefore both the audit object and the dispatch mechanism.

## Execution and telemetry

The only route remains `r3_8_post_delete_recovery`. It performs two official Cloudflare control-plane GET requests and never replays deletion.

The workflow writes accepted and final `M23_OPERATOR_STATUS` comments to locked issue #565. These records expose the run URL, run ID, exact head, authorization digest, final exit code and artifact name to the connected assistant.

## Fresh authorization

```text
operator_authorizations/m23/r3-8/post-delete-recovery-29521901629-v3.json
```

Authorization SHA-256:

```text
ccafc925c4db5f6398d3ac1fa45d63831e6eaa047cc3d09e725ceef8833a56ff
```

Contract SHA-256:

```text
039eee1a7a3731bb5942b5c556fe3db038a68d7c816b505de905c2683161fb29
```

## Authority boundary

The ledger accepts no arbitrary shell, workflow, branch, repository, issue, URL or message body. Production retrieval remains lexical and both blockers remain active. No Worker deletion/deployment, Qdrant/R2 access, blocker clearance, promotion or closure is authorized.
