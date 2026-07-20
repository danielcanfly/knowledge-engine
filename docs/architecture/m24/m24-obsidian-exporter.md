# M24 Obsidian Exporter

This advances #971 while production retrieval remains lexical.

The first exporter is a deterministic transform from the public `/v1/search`
response into an Obsidian-ready bundle. It emits a README, concept notes, source
notes, and a manifest. The export is meant for offline product review and Source
review preparation, not for production serving.

## Export Format

The bundle contains:

- `README.md` with release, request, and authority metadata;
- `concepts/*.md` notes for visible lexical search results;
- `sources/*.md` notes for bounded source viewers;
- `manifest.json` with file paths, content SHA-256 values, and authority flags.

Concept notes link to source notes with Obsidian wikilinks. Source notes preserve
the public citation ID, source card ID, concept ID, section ID, citation scope,
support type, locator fields, claim IDs, review status, derivation type, source
URI, snapshot availability, and integrity hash when present.

## Boundary

- production retrieval remains `lexical`;
- semantic answer serving remains disabled;
- semantic promotion remains disabled;
- hybrid retrieval remains disabled;
- exports are derived from bounded public search/source-viewer payloads only;
- raw evidence text, query vectors, retrieval internals, evaluation payloads,
  reviewer identities, storage keys, credentials, and arbitrary source snapshots
  are not exported;
- Source, pointer, R2, Qdrant, credential, traffic, and production mutations are
  unauthorized.

## Round-Trip Limitations

The export preserves review context, provenance pointers, and stable IDs. It is
not a canonical Source write format. Importing edited Obsidian notes back into
Source would require a later governed parser, review decision model, and separate
Source PR. This exporter does not authorize direct Source mutation.

## Validation

The implementation validates export paths, emits deterministic SHA-256 values for
every file, keeps a release/request-bound manifest, and has tests for replay
stability, provenance preservation, empty exports, and non-serving authority.
