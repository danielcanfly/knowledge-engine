# M14.4 Public Ask AI Interfaces

Status: implementation candidate  
Parent: #190  
Slice: #196  
Depends on: M14.1 #191, M14.2 #192, M14.3 #194  
Engine baseline: `bf52cf0ecbb10dc81cda72c80d0f1e39d0afb5af`

## Purpose

M14.4 exposes the governed M14 answer pipeline through three consistent product surfaces:

1. JSON API;
2. standalone chat page;
3. same-origin blog widget.

All three surfaces use the same `PublicAskRequest`, authorization check, runtime query, release binding, answer composition, citation payload and source-card formatter. The interfaces do not introduce an alternate answer engine.

## Interface discovery

Clients may inspect:

```text
GET /v1/ask/capabilities
```

The response schema is:

```text
knowledge-engine-public-interface/v1
```

It reports:

```text
surfaces
transports
session_mode
default_audience
same_origin_default
ask_path
stream_path
standalone_path
widget_script_path
supported_locales
max_query_characters
max_results
citation_markers
source_cards
stream_event_order
```

M14.4 advertises:

```text
surfaces: api, standalone_chat, blog_widget
transports: json, sse
session_mode: stateless
default_audience: public
same_origin_default: true
```

## JSON API

The existing endpoint remains unchanged:

```text
POST /v1/ask
```

It returns the complete M14.1-M14.3 JSON response. M14.4 does not fork or wrap this contract.

## Deterministic SSE response stream

The streaming endpoint is:

```text
POST /v1/ask/stream
Accept: text/event-stream
```

It accepts the same `PublicAskRequest` and executes the exact same `_execute_public_ask` function as the JSON route. Streaming begins only after authorization, retrieval, release binding and public payload construction succeed.

This is response-event streaming, not hidden model-token generation. The event order is deterministic:

```text
meta
answer zero or more times
citations
source_cards
done
```

### `meta`

```text
schema_version
request_id
release_id
status
audience
confidence
not_found_reason
session_mode
```

The stream schema is:

```text
knowledge-engine-public-interface-stream/v1
```

### `answer`

Each event contains:

```text
index
text
```

Answer chunks follow the deterministic paragraph boundaries already present in the public answer. They are not regenerated independently.

### `citations`

Contains the complete ordered M14.3 public citation list:

```json
{"items": []}
```

### `source_cards`

Contains the complete ordered M14.3 source-card list:

```json
{"items": []}
```

### `done`

Contains:

```text
request_id
status
event_count
```

Every SSE event receives a deterministic event ID derived from the public request ID and event index.

## Standalone chat

The standalone interface is:

```text
GET /ask?lang=en
GET /ask?lang=zh-TW
```

Unsupported locale values fail closed to English. The page:

- contains no third-party assets;
- loads the same widget script used by blog embedding;
- uses a restrictive Content Security Policy;
- permits network connections only to the same origin;
- disables framing;
- disables base URL mutation;
- disables referrer transmission;
- never embeds credentials or access tokens.

The page may display several turns in the current DOM, but each submission is an independent stateless request. Previous turns are not sent back to the server and do not alter retrieval.

## Blog widget

The widget script is:

```text
GET /embed/ask.js
```

Same-origin integration:

```html
<knowledge-ask
  data-locale="zh-TW"
  data-endpoint="/v1/ask/stream"
  data-max-results="5">
</knowledge-ask>
<script src="/embed/ask.js" defer></script>
```

The custom element:

- uses Shadow DOM to isolate layout;
- has no external dependency;
- uses the same SSE endpoint as the standalone page;
- submits only `query`, `max_results` and `audience: public`;
- sends credentials only under browser same-origin rules;
- rejects a configured endpoint whose origin differs from the page origin;
- renders all dynamic values with DOM `textContent`;
- never accepts HTML from answer, citation or source-card fields;
- opens source links with `noopener noreferrer`;
- stores no turn history in cookies, web storage or a server session.

Cross-origin embedding, origin allowlists and public authentication policy belong to M14.5.

## Presentation states

The widget maps public states to explicit UX:

- `answered`: show answer, confidence, release and source cards;
- `degraded`: show answer and explain that inspectable sources are unavailable;
- `not_found`: show a bounded no-supported-answer message;
- HTTP 401 or 403: show a bounded authorization message;
- HTTP 503: show a bounded service-unavailable message;
- other failure: show a generic request failure.

Raw exception text is never inserted into the page.

## Accessibility

The interfaces include:

- an explicit textarea label;
- keyboard-native form submission;
- a status region with `aria-live`;
- an answer turn region with `aria-live`;
- native links and disclosure controls for source cards;
- disabled controls while a request is active;
- responsive single-column behavior on narrow viewports.

## Cache and buffering policy

The standalone page and SSE response use:

```text
Cache-Control: no-store
```

The widget script uses a short public cache lifetime. The stream also sends:

```text
X-Accel-Buffering: no
X-Content-Type-Options: nosniff
```

## Governance boundary

M14.4 performs no Source write, release creation, production mutation, rollback, ledger append, connector call, arbitrary URL fetch, snapshot read, server-side conversation persistence or physical deletion.

It is a presentation and transport layer over the already governed immutable release query path.
