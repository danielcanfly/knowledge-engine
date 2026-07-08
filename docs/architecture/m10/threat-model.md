# M10 Intake Threat Model

## Assets

- raw source bytes;
- provenance and source identity;
- ACL/license metadata;
- R2 credentials and objects;
- canonical Source integrity;
- production release identity;
- operator and connector credentials;
- normalization/runtime availability.

## Trust boundaries

1. external source to connector;
2. connector to acquisition coordinator;
3. ephemeral acquisition spool to immutable R2;
4. raw snapshot to normalizer/parser;
5. normalized derivative to compilation admission;
6. intake evidence to Source review workflow.

All imported content is untrusted data.

## Threats and required controls

| Threat | Control |
|---|---|
| SSRF and internal-network access | HTTPS allow policy, DNS/IP validation before and after redirects, private/link-local/metadata IP denial |
| Credential leakage in URI/logs | strip userinfo, redact query secrets, structured sanitized errors, never persist headers/cookies |
| Mutable source / TOCTOU | connector-native version, ETag/blob/revision evidence, before/after stat, content hash, changed-during-read rejection |
| Truncated or partial content | byte-count verification, pagination completeness proof, decompression limits, typed truncation failure |
| Path traversal or symlink escape | allowed-root resolution, no path escape, lstat/realpath checks |
| Malicious PDF/archive | file-type sniffing, parser sandboxing, active-content checks, expansion/recursion limits |
| Prompt injection in content | preserve as data, findings recorded, no tool/network authority, security-review gate |
| Secret/PII ingestion | pre-snapshot scanning policy, quarantine/reject, sanitized evidence, no public default |
| ACL laundering | connector permission evidence, restrictive default, non-broadening validator, claim/source ACL lineage |
| License laundering | explicit license status and source, unresolved blocks admission |
| Hash/key collision or overwrite | SHA-256, conditional create, byte-exact verification, collision incident |
| Storage denial-of-service | size quotas, connector budgets, dedupe, rate limits, bounded retries |
| Malicious MIME declaration | independent sniffing, reported vs observed MIME retained separately |
| Replay/tampering | canonical JSON hashes, immutable objects, append-only event chain, idempotency tests |
| Connector supply-chain compromise | pinned dependency versions, connector version evidence, least-privilege credentials, isolated execution |
| Canonical/production mutation from intake | separate credentials, denied APIs, tests proving write boundaries |

## Secret handling policy

Source bytes are first acquired into bounded ephemeral storage. Hard secret-policy or malware failures occur before durable snapshot creation. Rejection evidence records only hash, size, stage, policy code, and sanitized context.

## Incident triggers

- immutable key contains mismatched bytes;
- source-head points to missing/invalid snapshot;
- ACL downgrade detected;
- raw object missing after put;
- connector returns private-network content;
- accepted derivative lacks provenance;
- production or canonical Source changes during an intake-only workflow.

Each trigger must fail closed and preserve non-secret evidence.
