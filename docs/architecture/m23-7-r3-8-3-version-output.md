# M23.7-R3.8.3 Wrangler version-output compatibility

## Trigger

The R3.8.2 operator successfully ran the macOS Bash 3.2-compatible resolver, but the real pinned Wrangler command returned a version format that did not contain the assumed literal `wrangler ` prefix. The attempt stopped before Worker absence verification, deployment, secret creation, Qdrant access or live observation.

## Bounded repair

The resolver now parses a bounded, non-persisted version response line. It accepts exactly one release-version line in any of these forms:

- bare `4.111.0`;
- `wrangler 4.111.0`;
- ANSI-wrapped versions of either form;
- the Wrangler emoji banner followed by `wrangler 4.111.0`.

The parser rejects zero or multiple version lines, duplicate lines, prerelease/build variants, wrong versions and output larger than 4096 bytes. The resolved invocation remains a Bash indexed array and `eval` remains forbidden.

## Real-client validation

The dedicated macOS exact-head job invokes the real network-fetched pinned package:

```text
npx --yes wrangler@4.111.0 --version
```

It then sources the repository resolver with the macOS system Bash 3.2 and requires the resolver to produce the exact pinned version. Fake command shims remain useful for adversarial cases but are no longer sufficient acceptance evidence.

## Preservation

This repair does not change the R3.8 runtime, diagnostic Worker, frozen query identities, quality metrics, target ranks, 1200 ms latency threshold or authority boundaries. It dispatches no deployment, secret mutation, Qdrant access or protected mutation.

Production retrieval remains lexical. Parent #520 remains open pending one complete real R3.8 result, evidence seal and independent reconciliation.
