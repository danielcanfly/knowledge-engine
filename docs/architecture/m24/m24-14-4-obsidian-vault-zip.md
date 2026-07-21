# M24.14.4 Obsidian Vault ZIP Candidate

M24.14.4 adds a deterministic downloadable Obsidian Vault ZIP to the internal
product deployment package.

The ZIP is generated from the release-pinned Obsidian export bundle and is
committed under:

`pilot/m24/internal-product-deployment/site/downloads/llm-wiki-m24-obsidian-vault.zip`

The Obsidian route links to that same-origin ZIP and continues to expose the
export manifest.

## Determinism

The ZIP builder uses:

- `ZIP_STORED` with no compression;
- lexicographic member order;
- fixed `1980-01-01T00:00:00` ZIP member timestamps;
- fixed `0644` file permissions;
- UTF-8 content from the release-pinned export bundle.

Repeated builds are byte-identical and recorded in
`pilot/m24/m24-14/obsidian-vault-zip/m24-14-4-obsidian-vault-zip.json`.

## Boundary

- production retrieval remains lexical;
- semantic promotion, semantic serving, hybrid retrieval, and production answer
  serving remain disabled;
- write-back is not authorized;
- no Cloudflare, DNS, Access, R2, Qdrant, production pointer, traffic,
  credential, Source, or Foundation mutation is performed.
