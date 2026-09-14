# Legacy Predecessor Profile Contract

Profile: `LEGACY_M25_RAW_TEXT_WITH_DERIVED_NORMALIZED_EMBEDDING_V1`.

Applicability is limited to the exact frozen release, pointer, production manifest, candidate
manifest, source commit, admission digest, M25 engine commit, collection, 4,197-point count,
and immutable semantic-input artifact. All legacy payload `text_sha256` values must match raw
artifact text. Normalized embedding-input hashes are reconstructed from that artifact with
M23 NFKC+strip normalization and retained as separate evidence.

The profile is collection-wide. Mixed populations fail. Unknown all-missing populations fail.
Provider/model must exactly equal `cloudflare-workers-ai` and `@cf/baai/bge-m3`. Aggregate
identity is domain-separated by profile and all three historical evidence digests.
