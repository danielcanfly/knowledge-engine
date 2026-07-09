# M14.5 Audience, Security and Abuse Controls

Status: implementation candidate  
Parent: #190  
Slice: #198  
Depends on: M14.1 #191, M14.2 #192, M14.3 #194, M14.4 #196  
Engine baseline: `8dae8a4a6fff5d66482214e53984f2160f2f57f6`

## Purpose

M14.5 turns the M14 public ask interfaces into a bounded public product surface without weakening internal query, refresh or release-control routes.

The security model is deliberately asymmetric:

```text
anonymous request -> public audience only
authenticated JWT -> exact governed audience claims
internal control route -> authenticated principal required
```

Anonymous access is not a development-mode shortcut. It creates a distinct unauthenticated principal with only the `public` audience.

## Authentication and audience rules

Public ask routes use optional public authentication:

```text
no bearer token + PUBLIC_ANONYMOUS_ENABLED=true
  -> subject: anonymous-public
  -> audiences: public
  -> authenticated: false

valid bearer token
  -> subject: JWT sub
  -> audiences: governed knowledge_audiences plus public
  -> authenticated: true
```

An anonymous principal can never request `internal`, `confidential` or `restricted`, even when development auth is otherwise disabled.

Elevated audience requests require both:

1. an authenticated principal;
2. the exact requested audience in that principal's governed audience set.

The following routes continue to use the strong principal dependency and never accept the anonymous public principal:

```text
GET  /v1/releases/current
POST /v1/releases/refresh
POST /v1/query
```

## Public edge middleware

All public assets and ask endpoints pass through one ASGI middleware:

```text
GET  /ask
GET  /embed/ask.js
GET  /v1/ask/capabilities
POST /v1/ask
POST /v1/ask/stream
```

The middleware performs:

- exact origin validation;
- bounded CORS preflight handling;
- request-body size enforcement;
- consistent public security headers;
- stable public error payloads for edge rejection.

It does not wrap internal query or release-control routes.

## Origin policy

Default behavior is same-origin.

Cross-origin browser requests are accepted only when the normalized origin exactly matches an entry in:

```text
PUBLIC_ALLOWED_ORIGINS
```

Entries must be absolute origins with no path, query, fragment or credentials. Wildcards are forbidden. Staging and production entries must use HTTPS.

Examples:

```text
valid:   https://www.danielcanfly.com
invalid: *
invalid: https://www.danielcanfly.com/blog
invalid: https://user:pass@example.com
invalid in production: http://example.com
```

Requests with no `Origin` header remain valid for server-to-server API clients. Browser `Origin: null` is rejected.

## CORS preflight

For public API paths, an allowed origin may receive a bounded `204` response advertising:

```text
GET, POST, OPTIONS
authorization, content-type
max-age: 300
```

The server never returns a wildcard origin. Cross-origin credentials are not enabled.

## Blog widget transport

The M14.4 widget may now target an allowlisted API origin.

Credential behavior is explicit:

```text
same-origin endpoint  -> credentials: same-origin
cross-origin endpoint -> credentials: omit
```

Therefore a cross-origin public widget can use anonymous public access, but cannot silently forward cookies or browser credentials. The API origin remains the final authority through exact CORS allowlisting.

## Request-body limit

The edge middleware enforces:

```text
PUBLIC_MAX_BODY_BYTES
```

The default is 16 KiB. Both declared `Content-Length` and streamed request chunks are checked before public ask execution.

Oversized requests return:

```text
HTTP 413
PUBLIC-QUERY-BODY-TOO-LARGE
```

## Rate limiting

A fixed-window in-process limiter protects public ask execution.

Defaults:

```text
PUBLIC_RATE_LIMIT_REQUESTS=30
PUBLIC_RATE_LIMIT_WINDOW_SECONDS=60
```

The key is a SHA-256 digest of:

- authenticated subject for JWT principals;
- anonymous client host for public anonymous principals.

The raw subject and raw client host are not logged.

A rejected request returns:

```text
HTTP 429
PUBLIC-QUERY-RATE-LIMITED
Retry-After: <remaining window seconds>
```

This limiter is intentionally process-local. Distributed rate limiting and CDN/WAF bot controls remain deployment concerns and are reported as unsupported in capabilities.

## Concurrency and timeout

Public ask execution uses a bounded thread executor and semaphore.

Defaults:

```text
PUBLIC_MAX_CONCURRENT_REQUESTS=8
PUBLIC_REQUEST_TIMEOUT_SECONDS=15
```

When capacity is exhausted:

```text
HTTP 429
PUBLIC-QUERY-OVERLOADED
Retry-After: 1
```

When execution exceeds the timeout:

```text
HTTP 504
PUBLIC-QUERY-TIMEOUT
Retry-After: 1
```

A timed-out worker retains its concurrency slot until the underlying read-only runtime operation actually finishes. This prevents timed-out work from multiplying beyond the configured capacity.

## Error contract

Public JSON and SSE routes document stable errors for:

```text
401 authentication required or invalid
403 audience or origin rejection
413 request body too large
429 rate limited or overloaded
503 release unavailable
504 execution timeout
```

All error payloads use:

```text
knowledge-engine-public-query/v1/error
```

Raw runtime exceptions, query text and authentication details are not returned.

## Rejection telemetry

Rejection logs contain only:

```text
reason
route class
authenticated boolean
HTTP status
```

They do not contain:

```text
query text
request body
bearer token
JWT claims
raw IP or client host
hashed client key
```

## Security headers

Public responses receive:

```text
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
```

The standalone page also receives:

```text
Cross-Origin-Opener-Policy: same-origin
```

The public widget script receives:

```text
Cross-Origin-Resource-Policy: cross-origin
```

The standalone CSP defined in M14.4 remains in force.

## Capability disclosure

`GET /v1/ask/capabilities` now returns a nested public security posture:

```text
anonymous_public_access
elevated_audience_requires_authentication
cors_mode
allowed_origin_count
wildcard_origins_allowed
cross_origin_credentials
rate_limit_requests
rate_limit_window_seconds
max_body_bytes
request_timeout_seconds
max_concurrent_requests
distributed_rate_limit
server_conversation_state
```

The response reveals counts and effective limits, never origin values, tokens, keys or deployment secrets.

## Configuration

```text
PUBLIC_ANONYMOUS_ENABLED=true
PUBLIC_ALLOWED_ORIGINS=
PUBLIC_RATE_LIMIT_REQUESTS=30
PUBLIC_RATE_LIMIT_WINDOW_SECONDS=60
PUBLIC_MAX_BODY_BYTES=16384
PUBLIC_REQUEST_TIMEOUT_SECONDS=15
PUBLIC_MAX_CONCURRENT_REQUESTS=8
```

All numeric values are range validated. Invalid security configuration fails startup validation rather than silently widening access.

## Governance boundary

M14.5 performs no Source write, release creation, production mutation, rollback, ledger append, connector call, arbitrary source fetch, snapshot read, conversation persistence or physical deletion.

The controls are an edge and execution boundary around the existing immutable public query path.
