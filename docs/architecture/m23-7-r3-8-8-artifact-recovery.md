# M23.7-R3.8.8 Artifact Recovery

## Incident

GitHub Actions run `29506217284` completed checkout, exact-head verification,
Python/Node setup and the remote operator wrapper. The evidence upload then failed
and no artifact was retained.

The evidence directory was named `.r3-8-remote-evidence`. `actions/upload-artifact@v4`
excludes hidden files by default. Combined with `if-no-files-found: error`, the
workflow treated the hidden evidence directory as empty. The final result step also
failed, so the operator exit class was not preserved by run metadata.

Classification:

```text
rejected_incomplete_remote_observation_evidence_loss
```

This is not a latency acceptance result. It cannot be sealed and it does not clear
`blocked_pending_retrieval_quality` or `blocked_pending_latency`.

## Repair

Observation artifacts now use `r3-8-remote-evidence`. Deletion artifacts use
`r3-8-deletion-evidence`. Both workflows explicitly keep hidden-file inclusion off
and fail when no non-hidden evidence exists.

The observation workflow now invokes a bounded stdlib entrypoint before importing
the remote operator. It writes `remote-entry.json` first. Import, startup or
preflight exceptions are converted into a privacy-safe bounded failure artifact.
Arbitrary exception text, service URLs, credentials and raw evidence are never
persisted.

## Recovery probe

The affected Worker name is deterministic:

```text
knowledge-engine-r3-8-29506217284
```

The recovery workflow performs only two Cloudflare control-plane GET requests:

```text
/accounts/{account}/workers/scripts/{worker}/versions
/accounts/{account}/workers/scripts/{worker}/deployments
```

It may report:

- `worker_absent`
- `worker_present`
- `worker_state_inconsistent`
- `worker_state_indeterminate`

The probe does not deploy or delete a Worker, update secrets, invoke the Worker
route, read Qdrant, read R2, or mutate production, pointer or Source state. Version
and deployment identities may be included in the privacy-safe recovery receipt so a
later governed cleanup can bind the exact orphan.

## Next legal decision

- If the Worker is absent, independently reconcile the absence and authorize a fresh
  observation from the then-current accepted main head.
- If the Worker is present, independently reconcile its exact identity and open a
  separate orphan-cleanup authorization before deletion.
- If state is inconsistent or indeterminate, do not retry, deploy or delete. Open a
  bounded diagnostic repair.

Run `29506217284` must never be rerun.
