# M23.7 R3.8.24 Fail-Closed Latency Evidence Reconciliation

## Run 29613277172

This reconciliation independently accepts the fail-closed evidence seal from
PR #886 for remote observation run `29613277172`.

The accepted seal digest is
`d19bab9011be58c39bc9f0d8d86da5637b61e47993e4c2f33434dd8c557b76d3`, and this
reconciliation digest is
`a9e4b5e76f3fff61641fd4741413974eb0a6170da6056785b15fb7be4d38a67f`.

The payload-selector repair restored quality parity: accepted metrics and
target ranks matched the R3.7/R3.8 contract exactly, and strict-zero mutation
gates remained accepted. The run still did not pass because
`worker_internal_shadow` failed at `1641 ms` against the unchanged maximum of
`1200 ms`.

Diagnostic Worker `knowledge-engine-r3-8-29613277172` remains retained and
requires separately governed cleanup before the next latency repair attempt.

No blocker is eligible for clearance. Production retrieval remains `lexical`,
and the next legal gate is retained worker cleanup.

## Run 29610393567

This reconciliation independently accepts the fail-closed evidence seal from
PR #877 for remote observation run `29610393567`.

The accepted seal digest is
`df97373c519c138c254965a6f91bed8c76af238b85ce7cbcc3dd51867c8669d6`, and this
reconciliation digest is
`56b8093a6df72d678faf381f4ddf95d6a11131d82ce25bc5ab6cb541b2d374c3`.

The top-10 dense-limit attempt did not pass. It failed accepted metric parity,
exact target-rank parity, and worker internal shadow latency. The diagnostic
Worker `knowledge-engine-r3-8-29610393567` remains retained and requires
separately governed cleanup.

No blocker is eligible for clearance. Production retrieval remains `lexical`,
and the next legal gate is retained worker cleanup.

## Run 29607698618

This reconciliation independently accepts the fail-closed latency evidence seal
from PR #868 for remote observation run `29607698618`.

The seal merged at `6d9964bfdb7653e847cf537f5af9149db347e944` and bound seal
digest `eb6c0ccadef07d0fae019a08dd1e5b67842f5895bb61cae5bd82b2a75c0f8112`.
The seal head `280d14ddf69b3b381914e1ca75ec479264ca4973` passed CI, M17,
M18, and the dedicated fail-closed latency evidence seal workflow.

The accepted result remains a complete failure, not a pass. Retrieval quality
and strict-zero mutation gates are accepted, but `worker_internal_shadow`
failed at `2078 ms` against the unchanged maximum of `1200 ms`.

Diagnostic worker `knowledge-engine-r3-8-29607698618` remains retained. Its
cleanup is required through a separate governed lifecycle before R3.8 can move
back to latency repair and fresh observation.

Production retrieval remains `lexical`. This reconciliation does not clear
blockers, authorize deletion, authorize fresh observation, authorize promotion,
or authorize parent or M23.7 closure.

## Run 29604923286

This reconciliation independently accepts the fail-closed latency evidence seal
from PR #859 for remote observation run `29604923286`.

The seal merged at `cf940aa6fb73e1e77a871287a135cd3ec64b8870` and bound seal
digest `31e27077f5c1edf42bf10858032280e2edf6c61eac5668eb62d93fc1a2338f8f`.
The seal head `565d64a0e9cc0ed21c7e77a5d5713b6142aaed9c` passed CI, M17,
M18, and the dedicated fail-closed latency evidence seal workflow.

The accepted result remains a complete failure, not a pass. Retrieval quality
and strict-zero mutation gates are accepted, but `worker_internal_shadow`
failed at `4839 ms` against the unchanged maximum of `1200 ms`.

Diagnostic worker `knowledge-engine-r3-8-29604923286` remains retained. Its
cleanup is required through a separate governed lifecycle before R3.8 can move
back to latency repair and fresh observation.

Production retrieval remains `lexical`. This reconciliation does not clear
blockers, authorize deletion, authorize fresh observation, authorize promotion,
or authorize parent or M23.7 closure.

## Run 29553221650

This reconciliation independently accepts the fail-closed latency evidence seal
from PR #677 for remote observation run `29553221650`.

The seal merged at `0fc57a04793705f8dfbcd4c5ab4f85512a5f696e` and bound seal
digest `a4200b040642a7544d549d80b4e64fd88e996c9209a15e7285ffcb17397e2fab`.
The seal head `1f6d1182ba49f1d6448b25fd41552ac8499c3634` passed CI, M17,
M18, and the dedicated fail-closed latency evidence seal workflow.

The accepted result remains a complete failure, not a pass. Retrieval quality
and strict-zero mutation gates are accepted, but `worker_internal_shadow`
failed at `1680 ms` against the unchanged maximum of `1200 ms`.

Diagnostic worker `knowledge-engine-r3-8-29553221650` remains retained. Its
cleanup is required through a separate governed lifecycle before R3.8 can move
back to latency repair and fresh observation.

Production retrieval remains `lexical`. This reconciliation does not clear
blockers, authorize deletion, authorize fresh observation, authorize promotion,
or authorize parent or M23.7 closure.
