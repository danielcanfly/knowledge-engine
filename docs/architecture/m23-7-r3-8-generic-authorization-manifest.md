# M23.7 R3.8 Generic Authorization Manifest

This change introduces a generic, data-driven authorization path for read-only
R3.8 recovery probes.

Run identity is now reviewed data under:

```text
pilot/m23/r3-8/authorizations/<run-id>.json
```

The manifest binds the run ID, affected Engine SHA, derived Worker name,
observation artifact digest, allowed actions, expiry and authority boundaries.
The generic executor validates the manifest self-digest before it reads the
Cloudflare control-plane versions and deployments collections. The receipt
records the probe Engine SHA separately so the affected run identity is not
confused with the reviewed executor commit.

This is a harness-efficiency repair only. It does not deploy, delete, replay an
observation, mutate secrets, access Qdrant or R2, clear blockers, promote
semantic retrieval, close parent issues, or authorize M23.7 closure.

After the current retained Worker cleanup, no further run-specific Python
adapter or workflow routing case is authorized for routine recovery probes.
