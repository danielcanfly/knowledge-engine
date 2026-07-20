# M23.7 R3.8 Placement Semantics v2

This repair corrects the placement proof boundary used by the one-shot R3.8
remote observation operator.

Cloudflare targeted Placement Hints may add `cf-placement` when placement is
visible to the response. A sanitized `remote` class means the invocation was
forwarded to the placed location. A sanitized `local` class means forwarding was
not required for that invocation. A sanitized `absent` class is now accepted as
bounded telemetry when service availability and application readiness are both
proven; it is not treated as Worker unhealthiness by itself. Unknown values
remain fail-closed.

The operator never persists the airport code, Qdrant hostname, service URL, or
credentials. The final receipt records only bounded placement classes and
whether routing was remote.

The frozen Worker request contract remains
`d081ab57a85b4ea813aeb813090b597340b8c3842ff78d7022d38501e6c282ba`.
The Worker-internal latency maximum remains exactly `1200 ms`; quality, target
rank parity, strict-zero gates, production retrieval, and all mutation
boundaries remain unchanged.

This repair grants no blocker clearance, promotion eligibility, parent closure,
or M23.7 closure by itself. Its current deterministic contract digest is
`4b32ddd0bfe236d5c501a1c2ecbcd2e409442a85117014388a6f6edc9f12f4c9`.
