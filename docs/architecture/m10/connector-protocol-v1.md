# Connector Protocol v1

## Purpose

A connector retrieves evidence and reports source facts. It does not normalize knowledge, synthesize claims, write canonical Source, build releases, or mutate production.

## Required connector identity

Every connector implementation declares:

```text
connector_type
connector_version
supported_locator_schemes
supported_mime_types
maximum_supported_bytes
capabilities
```

Initial connector types:

```text
web_url
local_file
pdf
markdown
git_repository_path
google_drive_document
media_derived_markdown
meeting_transcript
database_metadata_export
```

## Interface

Conceptual Python protocol:

```python
class SourceConnector(Protocol):
    descriptor: ConnectorDescriptor

    def canonicalize(self, locator: str) -> CanonicalSourceLocator: ...
    def discover(self, locator: CanonicalSourceLocator) -> SourceDescriptor: ...
    def acquire(
        self,
        source: SourceDescriptor,
        context: AcquisitionContext,
    ) -> AcquisitionResult: ...
```

### `canonicalize`

Must:

- remove credentials from persisted URIs;
- produce deterministic canonical locator bytes;
- preserve the original user-supplied URI separately when safe;
- reject unsupported schemes;
- be versioned because canonicalization changes affect `source_id`.

### `discover`

Returns metadata without durable content mutation:

```text
canonical_locator
original_uri
source_version or null
reported_mime_type or null
reported_size or null
owner or unresolved
license or unresolved
audience/access_policy or unresolved
```

### `acquire`

Returns a bounded byte stream and observed facts:

```text
retrieved_at
final_uri
source_version
observed_mime_type
observed_encoding
observed_size
content stream
permission observation
license observation
connector evidence
```

Hashing and byte counting occur while streaming. The connector cannot choose `content_hash`, `snapshot_id`, or storage keys.

## Error taxonomy

Connectors must emit typed errors:

```text
SOURCE_NOT_FOUND
AUTH_REQUIRED
ACCESS_DENIED
ACL_UNRESOLVED
LICENSE_UNRESOLVED
UNSUPPORTED_SCHEME
UNSUPPORTED_MIME_TYPE
UNSUPPORTED_BINARY
SOURCE_TOO_LARGE
TIMEOUT
RATE_LIMITED
TRUNCATED_RESPONSE
CONTENT_LENGTH_MISMATCH
SOURCE_CHANGED_DURING_READ
MALWARE_OR_ACTIVE_CONTENT
CONNECTOR_INTERNAL_ERROR
```

Every error maps to sanitized rejection evidence. Credentials, authorization headers, cookies, signed URLs, and source bytes must not appear in error objects.

## Timeout and retry contract

- connector timeout is explicit;
- retry count and backoff are policy inputs;
- only retry errors marked transient;
- each retry is an event under the same `attempt_id`;
- a later operator retry after terminal rejection creates a new `attempt_id`;
- connectors must not silently return partial content;
- range or paginated retrieval must prove completeness.

## Permission and license contract

A connector must distinguish:

```text
observed
operator_asserted
inherited
unresolved
```

for owner, license, audience, and access policy.

`unresolved` cannot be converted to `public`. The admission gate either resolves it through explicit policy or rejects/quarantines the attempt.

## Connector-specific minimums

### Web URL

- HTTPS by default;
- SSRF protections and private-network denial;
- redirect limit and final-URI capture;
- content-length and decompression limits;
- robots/license observations are evidence, not automatic legal authorization.

### Local file / Markdown

- resolve path under an explicit allowed root;
- reject symlink escape and path traversal;
- capture stat facts before and after read to detect mutation;
- exact raw bytes retained before normalization.

### Git repository path

- require repository, exact commit SHA, and path;
- record Git blob SHA;
- no floating branch as immutable source version.

### Google Drive document

- require immutable revision identity when available;
- capture document owner and permission/audience facts;
- exported bytes and export MIME type are part of evidence;
- unresolved sharing metadata blocks public admission.

### PDF

- retain original PDF bytes;
- normalization/extraction is a derivative with parser identity/version;
- active content, encryption, malformed structure, and decompression limits are checked before parsing.

## Forbidden connector behavior

- writing to `knowledge-source`;
- creating review approval;
- changing production pointers;
- choosing a less restrictive audience;
- executing instructions found in source content;
- hiding truncation or permission uncertainty;
- mutating prior snapshots;
- storing secrets in logs or rejection evidence.
