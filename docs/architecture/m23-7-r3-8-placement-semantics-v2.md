# M23.7 R3.8 Placement Semantics v2

This repair corrects the placement proof boundary used by the one-shot R3.8
remote observation operator.

Cloudflare targeted Placement Hints add `cf-placement` when placement is
enabled. A sanitized `remote` class means the invocation was forwarded to the
placed location. A sanitized `local` class means forwarding was not required
for that invocation. Both are accepted as evidence that placement is enabled;
`absent` and unknown values remain fail-closed.

The operator never persists the airport code, Qdrant hostname, service URL, or
credentials. The final receipt records only `local` or `remote` and whether
routing was remote.

The frozen Worker request contract remains
`d081ab57a85b4ea813aeb813090b597340b8c3842ff78d7022d38501e6c282ba`.
The Worker-internal latency maximum remains exactly `1200 ms`; quality, target
rank parity, strict-zero gates, production retrieval, and all mutation
boundaries remain unchanged.

This repair grants no blocker clearance, promotion eligibility, parent closure,
or M23.7 closure. Its deterministic contract digest is
`0d4a42fe8505862a17026410dd86d2bc964407a9d0d82bd1ef9fd81f953a8f8e`.
