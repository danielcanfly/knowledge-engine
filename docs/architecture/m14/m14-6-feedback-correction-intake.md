# M14.6 Feedback and Correction Intake

Status: implementation candidate  
Parent: #190  
Slice: #200  
Depends on: M14.1 #191, M14.2 #192, M14.3 #194, M14.4 #196, M14.5 #198  
Engine baseline: `2ac3fe6235146b9f8860f6e7bc9d63ffa1952d04`

## Purpose

M14.6 gives a public user a bounded way to report whether an answer was useful or needs correction. The signal remains bound to the exact public answer identity and enters a pending-review curation queue. It does not edit Source, create a Source package, dispatch a candidate or mutate production.

## Public endpoint

```text
POST /v1/feedback
```

The route uses the same M14.5 public principal, exact-origin CORS, body-size limit, fixed-window rate limiter, concurrency gate, timeout and security headers as `/v1/ask`.

## Feedback types

```text
helpful
unhelpful
factual_correction
citation_issue
missing_coverage
unsafe_or_inappropriate
other
```

Quick helpful and unhelpful signals do not require free text. Correction, citation, missing-coverage, unsafe and other signals require a bounded explanation.

A citation issue must identify a citation or source card. A factual correction must identify a concept or section. When both concept and section are present, the section must belong to that concept.

## Request contract

The request schema contains only:

```text
feedback_type
request_id
release_id
audience
message
citation_id
source_card_id
concept_id
section_id
reference_uri
locale
```

Unknown fields are rejected. In particular, the endpoint does not accept or collect:

```text
raw query
raw answer
email
name
phone
contact address
arbitrary metadata
attachment
```

The answer's `request_id` and `release_id` are required, so every signal remains bound to the exact answer release even after production advances.

## Audience rules

Anonymous principals may submit feedback only for the `public` audience. Internal, confidential or restricted feedback requires an authenticated principal with that exact governed audience.

Feedback authorization never grants access to answer content. It only authorizes the audience label attached to the correction signal.

## Privacy normalization

Free text is Unicode NFKC-normalized, whitespace-compacted and limited to 2,000 characters. The intake layer replaces:

```text
email addresses -> [redacted-email]
bearer credentials -> [redacted-token]
key, token, secret or password assignments -> [redacted-secret]
control characters -> space
```

The receipt reports only whether privacy redaction occurred. It does not expose the redaction list or stored message.

## Reference URI

`reference_uri` is optional and uses the same public URI policy as M14.3 source cards.

Only safe public HTTP(S) URIs are accepted. Localhost, private addresses, credential-bearing URLs and token or signature query parameters are rejected. Fragments are removed and accepted query parameters are deterministically sorted.

The intake service never fetches the URI.

## Deterministic feedback identity

The service derives a submitter scope by hashing the already hashed M14.5 client key with a feedback-specific namespace. The public feedback identity includes:

```text
submitter scope digest
feedback type
request ID
release ID
audience
sanitized message
citation and source-card IDs
concept and section IDs
safe reference URI
locale
```

The resulting public identity is:

```text
fb_{sha256-prefix}
```

The same submitter replaying the same sanitized signal receives the same feedback ID. Different submitters produce different identities, preserving independent signal counts without retaining raw subjects or client hosts.

## Immutable intake record

The first accepted signal writes exactly one immutable object:

```text
feedback/intake/v1/{feedback_id}.json
```

It contains the deterministic identity, sanitized content, answer bindings, a feedback-specific submitter digest and explicit governance flags:

```text
review_state: pending_review
source_write_allowed: false
candidate_dispatch_allowed: false
production_write_allowed: false
ledger_append_allowed: false
```

The object is created with `only_if_absent`. It is never overwritten or deleted by the M14.6 code path.

## Curation queue envelope

The intake also publishes an immutable queue envelope:

```text
feedback/curation-queue/v1/{feedback_id}.json
```

The queue envelope contains:

```text
feedback ID
intake SHA-256
created time
state: pending_review
proposed_action: review_feedback
all write permissions false
```

This envelope is a handoff to a later governed curation workflow, not an approval or edit authorization.

## Interrupted-write healing

The intake record is written before the queue envelope. If queue publication fails after intake creation, the request fails safely. Replaying the same signal detects the immutable intake, verifies its identity and publishes the missing queue envelope using the original received time.

A conflicting intake or queue identity fails closed with an integrity error.

## Receipt contract

Successful intake returns HTTP 202 and:

```text
schema_version
feedback_id
status
feedback_type
request_id
release_id
audience
received_at
curation_status
privacy_redactions_applied
source_write_performed
production_write_performed
```

`status` is:

```text
accepted
or
duplicate
```

The receipt never exposes object keys, intake hashes, queue hashes, submitter digests or stored text. Source and production write flags are always false.

## Public widget

The M14.4 widget now renders:

```text
Helpful
Not helpful
Suggest a correction
```

The correction control uses a bounded textarea and submits only the public answer identity, feedback type, optional message and available citation, source-card, concept or section IDs. It never sends the original query or answer text.

Same-origin feedback requests use `credentials: same-origin`. Cross-origin feedback requests omit credentials and remain subject to the M14.5 exact origin allowlist.

## Capability disclosure

`GET /v1/ask/capabilities` now advertises:

```text
feedback path
supported feedback types
immutable intake
pending-review queue
direct Source write: false
direct production write: false
contact identity collected: false
raw query collected: false
raw answer collected: false
attachments supported: false
```

## Governance boundary

M14.6 performs no Canonical Source write, Source package creation, Source PR creation, candidate dispatch, production promotion, rollback, physical deletion or permanent-ledger append.

A feedback signal becomes actionable only after a separate governed review and the existing Source-to-production lifecycle.
