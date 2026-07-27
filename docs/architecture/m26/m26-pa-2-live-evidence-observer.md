# M26.PA.2 Live Evidence Observer

The GitHub connector available to the executing subagent exposes pull-request workflow runs
but not repository push-run listing. This observer closes that evidence gap without receiving
R2, Qdrant, provider, or production credentials.

It is bound to main head `94b7d9d81ab3f56f62df25a6722bed5f2c038347`, workflow
`M26.PA.2 Exact Live Read-Only Evidence`, artifact
`m26-pa-2-live-read-only-evidence-attempt-1`, and issue `#1186`.

The observer uses only GitHub metadata authority:

- Actions read, to locate the exact push run and artifact
- Contents read, to validate the strict receipt schemas
- Issues write, to post one sanitized observation to issue `#1186`

It cannot rerun the live workflow. It has no live data credentials and no repository write
permission. It validates receipt schema and self-digest before posting run, artifact, release,
population, pagination, sample, and non-mutation evidence. A failed live run is reported as
failed closed rather than repaired or retried.
