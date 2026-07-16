# M23.7-R3.8.5 Wrangler structured deploy-target resolution

## Trigger

R3.8.4 replaced the pre-deploy direct REST Worker-absence check with a Wrangler-authenticated versions probe after the direct control-plane request returned HTTP 403.

The operator still had a second direct REST call after deployment to resolve the account workers.dev subdomain. R3.8.5 removes that second bearer-path dependency before another operator attempt.

## Structured output source

Wrangler supports `WRANGLER_OUTPUT_FILE_PATH`. A successful deploy appends a JSON-lines entry with:

- `type = deploy`;
- output schema `version = 1`;
- the Worker name and version identity;
- HTTP trigger `targets`.

The operator keeps this file in its existing temporary directory and deletes it during cleanup.

## Validation

The parser requires exactly one deploy record for the exact diagnostic Worker name and rejects Worker-name override. It requires one non-empty version ID and exactly one target.

The target must be an HTTPS origin whose hostname is:

```text
<exact-worker-name>.<single-account-subdomain>.workers.dev
```

Credentials, ports, query strings, fragments, non-root paths, custom domains, multiple targets, malformed JSON, duplicate deploy records and output larger than 65,536 bytes are rejected.

The validated URL is printed only to the operator process. It is not written to Git, receipts, evidence or durable logs.

## Preserved boundary

R3.8 runtime, Worker source, frozen queries, quality thresholds, the 1200 ms latency threshold, Wrangler version parser and Worker absence probe remain unchanged. This hotfix does not deploy a Worker, create secrets, access Qdrant, clear blockers, grant promotion eligibility or close parent #474.
