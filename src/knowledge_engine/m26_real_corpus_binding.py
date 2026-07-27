from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import httpx
from jsonschema import Draft202012Validator
from .errors import IntegrityError
ENTRY_PATH = 'pilot/m26/m26-pa-2-entry-contract.json'
POLICY_PATH = 'pilot/m26/m26-pa-2-retrieval-policy.json'
REGISTRY_PATH = 'pilot/m26/m26-pa-2-contract-registry.json'
CONTRACT_SCHEMA_PATH = 'schemas/m26-pa-2-contracts-v1.schema.json'
RECEIPT_SCHEMA_PATH = 'schemas/m26-pa-2-real-corpus-receipt-v1.schema.json'
FAILURE_SCHEMA_PATH = 'schemas/m26-pa-2-failure-receipt-v1.schema.json'
G0_ACCEPTANCE_PATH = 'pilot/m26/m26-g0-acceptance.json'
M25_RECONCILIATION_PATH = 'pilot/m25/m25-final-reconciliation.json'
SAFE_HEX_40 = re.compile('^[0-9a-f]{40}$')
SAFE_HEX_64 = re.compile('^[0-9a-f]{64}$')
RFC3339_UTC = re.compile('^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$')
RAW_KEY_PATTERN = re.compile('(?i)(^|[_-])(text|body|content|excerpt|prompt|markdown|document|chunk|passage|raw|html)([_-]|$)')
SECRET_KEY_PATTERN = re.compile('(?i)(api[_-]?key|secret|password|authorization|bearer|access[_-]?token|credential|private[_-]?key)')
SECRET_VALUE_PATTERNS = (re.compile('(?i)\\bbearer\\s+[a-z0-9._~+/=-]{8,}'), re.compile('\\bsk-[A-Za-z0-9_-]{16,}\\b'), re.compile('\\bgh[pousr]_[A-Za-z0-9_]{20,}\\b'), re.compile('\\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{8,}\\b'))
MUTATION_METHOD_NAMES = frozenset({'put', 'delete', 'write', 'upsert', 'set', 'patch', 'upload', 'create', 'update', 'remove', 'truncate'})

class RealCorpusBindingError(IntegrityError):

    def __init__(self, code: str, message: str, *, category: str='integrity', retryable: bool=False) -> None:
        super().__init__(f'{code} {message}')
        self.code = code
        self.safe_message = message
        self.category = category
        self.retryable = retryable

@dataclass(frozen=True)
class ReadResponse:
    payload: Mapping[str, Any]
    attempts: int = 1

@runtime_checkable
class ReadOnlyObjectStore(Protocol):
    capabilities: frozenset[str]
    credential_scope: str
    credential_contract_sha256: str

    def get(self, key: str) -> bytes:
        ...

@runtime_checkable
class ReadOnlyQdrantClient(Protocol):
    capabilities: frozenset[str]
    credential_scope: str
    credential_contract_sha256: str

    def count(self, *, collection: str, query_filter: Mapping[str, Any], timeout_seconds: float) -> ReadResponse:
        ...

    def scroll(self, *, collection: str, request: Mapping[str, Any], timeout_seconds: float) -> ReadResponse:
        ...

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))

def _failure(code: str, message: str, *, category: str='integrity', retryable: bool=False) -> RealCorpusBindingError:
    return RealCorpusBindingError(code, message, category=category, retryable=retryable)

def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _failure('M26-PA2-001', f'{label} must be an object')
    return value

def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise _failure('M26-PA2-002', f'{label} must be an array')
    return value

def _strict_keys(value: Mapping[str, Any], *, label: str, required: set[str], allowed: set[str] | None=None) -> None:
    observed = set(value)
    permitted = required if allowed is None else allowed
    missing = required - observed
    unknown = observed - permitted
    if missing:
        raise _failure('M26-PA2-003', f'{label} is missing required fields')
    if unknown:
        raise _failure('M26-PA2-004', f'{label} contains unknown fields')

def _decode_json_bytes(data: bytes, *, label: str, maximum_bytes: int) -> dict[str, Any]:
    if len(data) > maximum_bytes:
        raise _failure('M26-PA2-005', f'{label} exceeds the bounded byte limit')
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _failure('M26-PA2-006', f'{label} is invalid JSON') from exc
    return _object(value, label)

def load_json(path: Path) -> dict[str, Any]:
    try:
        return _decode_json_bytes(path.read_bytes(), label=path.as_posix(), maximum_bytes=4 * 1024 * 1024)
    except OSError as exc:
        raise _failure('M26-PA2-007', 'required local artifact is unavailable') from exc

def verify_self_digest(value: Mapping[str, Any], label: str) -> None:
    expected = value.get('self_sha256')
    if not isinstance(expected, str) or not SAFE_HEX_64.fullmatch(expected):
        raise _failure('M26-PA2-008', f'{label} self digest is missing or malformed')
    candidate = dict(value)
    candidate['self_sha256'] = ''
    if canonical_sha256(candidate) != expected:
        raise _failure('M26-PA2-009', f'{label} self digest mismatch')

def _validate_schema(instance: Mapping[str, Any], schema: Mapping[str, Any], label: str) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.absolute_path))
    if errors:
        raise _failure('M26-PA2-010', f'{label} strict schema validation failed')

def _validate_schema_document(schema: Mapping[str, Any], label: str) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise _failure('M26-PA2-011', f'{label} is not a valid Draft 2020-12 schema') from exc

def _validate_predecessors(root: Path, entry: Mapping[str, Any]) -> None:
    predecessors = _object(entry.get('predecessors'), 'entry predecessors')
    g0 = load_json(root / G0_ACCEPTANCE_PATH)
    m25 = load_json(root / M25_RECONCILIATION_PATH)
    verify_self_digest(g0, 'G0 acceptance')
    verify_self_digest(m25, 'M25 reconciliation')
    expected = {'g0_status': 'm26_g0_milestone_reconciliation_accepted', 'pa1_status': 'm26_pa_1_production_activation_authority_freeze_accepted', 'g0_main_seal_sha': '728df7da4e6b9320c25abb904a65a32b15e62bb1', 'g0_acceptance_self_sha256': g0['self_sha256'], 'm25_status': 'm25_closed', 'm25_final_reconciliation_self_sha256': m25['self_sha256'], 'm25_final_reconciliation_merge_sha': m25['closure_pr']['merge_sha'] if isinstance(m25.get('closure_pr'), dict) else ''}
    for key, expected_value in expected.items():
        if predecessors.get(key) != expected_value:
            raise _failure('M26-PA2-012', 'accepted predecessor identity mismatch')
    canonical_statuses = _object(g0.get('canonical_statuses'), 'G0 canonical statuses')
    if g0.get('status') != expected['g0_status'] or canonical_statuses.get('g0') != expected['g0_status'] or canonical_statuses.get('pa1') != expected['pa1_status']:
        raise _failure('M26-PA2-013', 'G0 or PA.1 is not accepted')
    if m25.get('result') != 'm25_closed':
        raise _failure('M26-PA2-014', 'M25 is not formally closed')

def _validate_registry(root: Path, *, entry: Mapping[str, Any], policy: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    artifacts = _object(registry.get('artifacts'), 'contract registry artifacts')
    expected_artifacts = {'entry_contract_sha256': canonical_sha256(entry), 'retrieval_policy_sha256': canonical_sha256(policy)}
    if artifacts != expected_artifacts:
        raise _failure('M26-PA2-015', 'contract registry child digest mismatch')
    schemas = _object(registry.get('schemas'), 'contract registry schemas')
    expected_schemas = {'contracts_schema_sha256': sha256_bytes((root / CONTRACT_SCHEMA_PATH).read_bytes()), 'receipt_schema_sha256': sha256_bytes((root / RECEIPT_SCHEMA_PATH).read_bytes()), 'failure_schema_sha256': sha256_bytes((root / FAILURE_SCHEMA_PATH).read_bytes())}
    if schemas != expected_schemas:
        raise _failure('M26-PA2-016', 'contract registry schema digest mismatch')

def validate_pa2_contracts(root: Path) -> dict[str, Any]:
    contract_schema = load_json(root / CONTRACT_SCHEMA_PATH)
    receipt_schema = load_json(root / RECEIPT_SCHEMA_PATH)
    failure_schema = load_json(root / FAILURE_SCHEMA_PATH)
    for label, schema in (('contracts schema', contract_schema), ('receipt schema', receipt_schema), ('failure schema', failure_schema)):
        _validate_schema_document(schema, label)
    entry = load_json(root / ENTRY_PATH)
    policy = load_json(root / POLICY_PATH)
    registry = load_json(root / REGISTRY_PATH)
    for label, value in (('entry contract', entry), ('retrieval policy', policy), ('contract registry', registry)):
        verify_self_digest(value, label)
        _validate_schema(value, contract_schema, label)
    _validate_predecessors(root, entry)
    _validate_registry(root, entry=entry, policy=policy, registry=registry)
    authority = _object(entry.get('authority'), 'entry authority')
    if authority.get('non_live_p0_p1_repair') is not True:
        raise _failure('M26-PA2-017', 'non-live repair authority is missing')
    if any((value for key, value in authority.items() if key != 'non_live_p0_p1_repair')):
        raise _failure('M26-PA2-018', 'PA.2 authority escalation detected')
    selector = policy['qdrant']['with_payload']
    allowlist = policy['payload']['allowlist']
    if selector != allowlist or len(selector) != len(set(selector)):
        raise _failure('M26-PA2-019', 'payload selector is not the exact allowlist')
    if policy['qdrant']['with_vector'] is not False:
        raise _failure('M26-PA2-020', 'vectors must remain disabled')
    return {'schema_version': 'knowledge-engine-m26-pa-2-non-live-evidence/v1', 'status': 'm26_pa_2_non_live_repair_contracts_valid', 'stage_id': 'M26.PA.2', 'accepted': False, 'live_execution': False, 'provider_calls': False, 'answer_generation': False, 'production_mutation': False, 'entry_contract_sha256': canonical_sha256(entry), 'retrieval_policy_sha256': canonical_sha256(policy), 'contract_registry_sha256': canonical_sha256(registry), 'receipt_schema_sha256': sha256_bytes((root / RECEIPT_SCHEMA_PATH).read_bytes()), 'failure_schema_sha256': sha256_bytes((root / FAILURE_SCHEMA_PATH).read_bytes()), 'payload_field_count': len(allowlist), 'expected_point_count': policy['qdrant']['expected_point_count'], 'legacy_candidate_merged': False}

def write_non_live_evidence(root: Path, output: Path) -> None:
    report = validate_pa2_contracts(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pretty_bytes(report))

def _credential_contract_digest(*, surface: str, operations: Sequence[str], secret_names: Sequence[str]) -> str:
    return canonical_sha256({'surface': surface, 'scope': 'read_only', 'allowed_operations': list(operations), 'secret_names': list(secret_names)})

def _assert_read_only_surface(subject: Any, *, label: str, expected_capabilities: frozenset[str], expected_credential_digest: str) -> None:
    capabilities = getattr(subject, 'capabilities', None)
    if capabilities != expected_capabilities:
        raise _failure('M26-PA2-021', f'{label} read-only capability mismatch', category='authority')
    if getattr(subject, 'credential_scope', None) != 'read_only':
        raise _failure('M26-PA2-022', f'{label} credential is not read-only', category='authority')
    if getattr(subject, 'credential_contract_sha256', None) != expected_credential_digest:
        raise _failure('M26-PA2-023', f'{label} credential contract mismatch', category='authority')
    for name in MUTATION_METHOD_NAMES:
        if callable(getattr(subject, name, None)):
            raise _failure('M26-PA2-024', f'{label} exposes a mutation method', category='authority')

def _safe_url(url: str, *, label: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or (parsed.password is not None) or parsed.query or parsed.fragment:
        raise _failure('M26-PA2-025', f'{label} URL is not credential-safe', category='security')
    return url.rstrip('/')

class Boto3ReadOnlyObjectStore:
    capabilities = frozenset({'get'})
    credential_scope = 'read_only'

    def __init__(self, *, endpoint_url: str, bucket: str, access_key_id: str, secret_access_key: str, region: str='auto') -> None:
        import boto3
        from botocore.config import Config
        self.credential_contract_sha256 = _credential_contract_digest(surface='r2', operations=('get',), secret_names=('R2_ACCESS_KEY_ID_READ', 'R2_SECRET_ACCESS_KEY_READ'))
        self._bucket = bucket
        self._client = boto3.client('s3', endpoint_url=_safe_url(endpoint_url, label='R2 endpoint'), aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key, region_name=region, config=Config(signature_version='s3v4', retries={'max_attempts': 1, 'mode': 'standard'}, connect_timeout=10, read_timeout=30, request_checksum_calculation='when_required', response_checksum_validation='when_required'))

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response['Body'].read()

class HttpxReadOnlyQdrantClient:
    capabilities = frozenset({'count', 'scroll'})
    credential_scope = 'read_only'

    def __init__(self, *, base_url: str, api_key: str, maximum_retries: int=1, sleeper: Callable[[float], None]=time.sleep, transport: httpx.BaseTransport | None=None) -> None:
        if maximum_retries < 0 or maximum_retries > 1:
            raise _failure('M26-PA2-026', 'Qdrant retry ceiling must be zero or one')
        self.credential_contract_sha256 = _credential_contract_digest(surface='qdrant', operations=('count', 'scroll'), secret_names=('QDRANT_READ_ONLY_API_KEY',))
        self._base_url = _safe_url(base_url, label='Qdrant endpoint')
        self._api_key = api_key
        self._maximum_retries = maximum_retries
        self._sleeper = sleeper
        self._transport = transport

    def _request(self, *, collection: str, operation: str, body: Mapping[str, Any], timeout_seconds: float) -> ReadResponse:
        if operation not in self.capabilities:
            raise _failure('M26-PA2-027', 'Qdrant operation is not read-only', category='authority')
        escaped = urllib.parse.quote(collection, safe='')
        url = f'{self._base_url}/collections/{escaped}/points/{operation}'
        attempts = 0
        while True:
            attempts += 1
            try:
                with httpx.Client(timeout=timeout_seconds, transport=self._transport) as client:
                    response = client.post(url, headers={'api-key': self._api_key, 'Accept': 'application/json'}, json=dict(body))
            except httpx.TimeoutException as exc:
                if attempts <= self._maximum_retries:
                    self._sleeper(0.0)
                    continue
                raise _failure('M26-PA2-028', 'Qdrant read timed out', category='transport', retryable=True) from exc
            except httpx.HTTPError as exc:
                raise _failure('M26-PA2-029', 'Qdrant transport failed', category='transport', retryable=False) from exc
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempts <= self._maximum_retries:
                    self._sleeper(0.0)
                    continue
                raise _failure('M26-PA2-030', 'Qdrant retry ceiling reached', category='transport', retryable=response.status_code == 429)
            if response.status_code < 200 or response.status_code >= 300:
                raise _failure('M26-PA2-031', 'Qdrant returned a non-success status', category='transport', retryable=False)
            try:
                payload = response.json()
            except ValueError as exc:
                raise _failure('M26-PA2-032', 'Qdrant returned malformed JSON') from exc
            return ReadResponse(payload=_object(payload, 'Qdrant response'), attempts=attempts)

    def count(self, *, collection: str, query_filter: Mapping[str, Any], timeout_seconds: float) -> ReadResponse:
        return self._request(collection=collection, operation='count', body={'exact': True, 'filter': dict(query_filter)}, timeout_seconds=timeout_seconds)

    def scroll(self, *, collection: str, request: Mapping[str, Any], timeout_seconds: float) -> ReadResponse:
        return self._request(collection=collection, operation='scroll', body=request, timeout_seconds=timeout_seconds)

def _qdrant_filter(values: Mapping[str, Any]) -> dict[str, Any]:
    return {'must': [{'key': key, 'match': {'value': value}} for key, value in sorted(values.items())]}

def _scan_credential_url(value: str) -> None:
    if '://' not in value:
        return
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise _failure('M26-PA2-033', 'payload contains a malformed URL', category='security') from exc
    sensitive_query = any((SECRET_KEY_PATTERN.search(key) for key, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)))
    if parsed.username is not None or parsed.password is not None or sensitive_query:
        raise _failure('M26-PA2-034', 'payload contains a credential-bearing URL', category='security')

def _recursive_payload_scan(value: Any, *, key: str | None=None) -> None:
    if key is not None:
        if SECRET_KEY_PATTERN.search(key):
            raise _failure('M26-PA2-035', 'payload contains a secret-like key', category='security')
        if key != 'text_sha256' and RAW_KEY_PATTERN.search(key):
            raise _failure('M26-PA2-036', 'payload contains a raw-text-like key', category='security')
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                raise _failure('M26-PA2-037', 'payload contains a non-string key')
            _recursive_payload_scan(child_value, key=child_key)
        return
    if isinstance(value, list):
        for child_value in value:
            _recursive_payload_scan(child_value)
        return
    if isinstance(value, str):
        if len(value) > 1024:
            raise _failure('M26-PA2-038', 'payload string exceeds the bounded limit')
        _scan_credential_url(value)
        if any((pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)):
            raise _failure('M26-PA2-039', 'payload contains a secret-like value', category='security')

def _validate_artifact_inventory(manifest: Mapping[str, Any], policy: Mapping[str, Any], release_id: str) -> tuple[int, str]:
    artifacts = _list(manifest.get('artifacts'), 'manifest artifacts')
    inventory_policy = policy['manifest']['artifact_inventory']
    if len(artifacts) < inventory_policy['minimum_count']:
        raise _failure('M26-PA2-040', 'manifest artifact inventory is incomplete')
    keys: set[str] = set()
    kinds: set[str] = set()
    normalized: list[dict[str, Any]] = []
    required_fields = {'kind', 'key', 'sha256', 'bytes', 'media_type', 'audiences', 'required'}
    for raw in artifacts:
        artifact = _object(raw, 'manifest artifact')
        _strict_keys(artifact, label='manifest artifact', required=required_fields)
        kind = artifact['kind']
        key = artifact['key']
        digest = artifact['sha256']
        byte_count = artifact['bytes']
        audiences = artifact['audiences']
        if not isinstance(kind, str) or not kind or len(kind) > 128:
            raise _failure('M26-PA2-041', 'manifest artifact kind is invalid')
        if not isinstance(key, str) or not key.startswith(f'releases/{release_id}/'):
            raise _failure('M26-PA2-042', 'manifest artifact key is outside the release')
        relative = key.removeprefix(f'releases/{release_id}/')
        if not relative or '..' in Path(relative).parts:
            raise _failure('M26-PA2-043', 'manifest artifact key is unsafe')
        if key in keys:
            raise _failure('M26-PA2-044', 'manifest artifact key is duplicated')
        if kind in kinds:
            raise _failure('M26-PA2-045', 'manifest artifact kind is duplicated')
        if not isinstance(digest, str) or not SAFE_HEX_64.fullmatch(digest):
            raise _failure('M26-PA2-046', 'manifest artifact digest is malformed')
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
            raise _failure('M26-PA2-047', 'manifest artifact byte count is invalid')
        if artifact['required'] is not True:
            raise _failure('M26-PA2-048', 'manifest artifact is not required')
        if not isinstance(audiences, list) or not audiences or (not all((isinstance(item, str) and item for item in audiences))):
            raise _failure('M26-PA2-049', 'manifest artifact audiences are invalid')
        keys.add(key)
        kinds.add(kind)
        normalized.append(dict(artifact))
    required_kinds = set(inventory_policy['required_kinds'])
    if not required_kinds.issubset(kinds):
        raise _failure('M26-PA2-050', 'manifest required artifact kind is missing')
    normalized.sort(key=lambda item: (item['key'], item['kind']))
    return (len(normalized), canonical_sha256(normalized))

def _validate_pointer(*, pointer_bytes: bytes, entry: Mapping[str, Any]) -> dict[str, Any]:
    identity = entry['production_identity']
    if sha256_bytes(pointer_bytes) != identity['pointer_sha256']:
        raise _failure('M26-PA2-051', 'production pointer digest drift')
    pointer = _decode_json_bytes(pointer_bytes, label='production pointer', maximum_bytes=64 * 1024)
    required = {'schema_version', 'channel', 'release_id', 'manifest_key', 'manifest_sha256', 'promoted_at', 'promotion_schema_version', 'source_candidate_channel', 'source_candidate_manifest_sha256', 'production_authority', 'public_production_traffic_mutated'}
    _strict_keys(pointer, label='production pointer', required=required)
    expected = {'schema_version': '1.0', 'channel': 'production', 'release_id': identity['release_id'], 'manifest_key': identity['manifest_key'], 'manifest_sha256': identity['manifest_sha256'], 'source_candidate_manifest_sha256': identity['candidate_manifest_sha256'], 'production_authority': True, 'public_production_traffic_mutated': False}
    for key, value in expected.items():
        if pointer.get(key) != value:
            raise _failure('M26-PA2-052', 'production pointer identity drift')
    return pointer

def _validate_manifest(*, manifest_bytes: bytes, entry: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[dict[str, Any], int, str]:
    identity = entry['production_identity']
    if sha256_bytes(manifest_bytes) != identity['manifest_sha256']:
        raise _failure('M26-PA2-053', 'production manifest digest drift')
    manifest = _decode_json_bytes(manifest_bytes, label='production manifest', maximum_bytes=4 * 1024 * 1024)
    required = {'schema_version', 'release_id', 'status', 'authority', 'identities', 'counts', 'artifacts', 'production_promotion'}
    if not required.issubset(manifest):
        raise _failure('M26-PA2-054', 'production manifest required surface is incomplete')
    if manifest.get('schema_version') != 'knowledge-engine-release/v1':
        raise _failure('M26-PA2-055', 'production manifest schema drift')
    if manifest.get('release_id') != identity['release_id']:
        raise _failure('M26-PA2-056', 'production manifest release drift')
    if manifest.get('status') != 'production':
        raise _failure('M26-PA2-057', 'production manifest status drift')
    authority = _object(manifest.get('authority'), 'manifest authority')
    expected_authority = {'production_pointer_authorized': True, 'public_production_traffic_authorized': False}
    for key, expected in expected_authority.items():
        if authority.get(key) is not expected:
            raise _failure('M26-PA2-058', 'production manifest authority drift')
    identities = _object(manifest.get('identities'), 'manifest identities')
    expected_identities = {'engine_commit_sha': identity['engine_sha'], 'source_commit_sha': identity['source_sha'], 'foundation_commit_sha': identity['foundation_sha'], 'admission_sha256': identity['admission_sha256']}
    for key, expected in expected_identities.items():
        if identities.get(key) != expected:
            raise _failure('M26-PA2-059', 'production manifest identity drift')
    counts = _object(manifest.get('counts'), 'manifest counts')
    if counts != policy['expected_counts']:
        raise _failure('M26-PA2-060', 'production manifest population drift')
    artifact_count, artifact_inventory_sha256 = _validate_artifact_inventory(manifest, policy, identity['release_id'])
    return (manifest, artifact_count, artifact_inventory_sha256)

def _validate_qdrant_envelope(value: Mapping[str, Any], operation: str) -> dict[str, Any]:
    _strict_keys(value, label=f'Qdrant {operation} response', required={'status', 'result'}, allowed={'status', 'result', 'time', 'usage'})
    if value.get('status') != 'ok':
        raise _failure('M26-PA2-061', f'Qdrant {operation} returned non-ok')
    return _object(value.get('result'), f'Qdrant {operation} result')

def _validate_payload(payload: Mapping[str, Any], *, policy: Mapping[str, Any]) -> dict[str, Any]:
    _recursive_payload_scan(payload)
    allowlist = policy['payload']['allowlist']
    allowed = set(allowlist)
    observed = set(payload)
    if not observed.issubset(allowed):
        raise _failure('M26-PA2-062', 'Qdrant payload contains an unexpected field')
    required = set(policy['payload']['required_fields'])
    if not required.issubset(observed):
        raise _failure('M26-PA2-063', 'Qdrant payload identity field is missing')
    if any((isinstance(value, (Mapping, list)) for value in payload.values())):
        raise _failure('M26-PA2-064', 'Qdrant payload contains nested material')
    expected_filter = policy['qdrant']['filter']
    for key, expected in expected_filter.items():
        if payload.get(key) != expected:
            raise _failure('M26-PA2-065', 'Qdrant payload authority identity drift')
    for key in ('section_id', 'source_id', 'article_id'):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value or len(value) > 512):
            raise _failure('M26-PA2-066', 'Qdrant payload identifier is invalid')
    text_digest = payload.get('text_sha256')
    if not isinstance(text_digest, str) or not SAFE_HEX_64.fullmatch(text_digest):
        raise _failure('M26-PA2-067', 'Qdrant text digest is invalid')
    return {key: payload[key] for key in allowlist if key in payload}

def _point_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _failure('M26-PA2-068', 'Qdrant point ID is invalid')
    result = str(value)
    if not result or len(result) > 256:
        raise _failure('M26-PA2-069', 'Qdrant point ID is invalid')
    return result

def _sample_entry(point_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    article_id = payload.get('article_id')
    return {'point_id_sha256': sha256_bytes(point_id.encode('utf-8')), 'section_id_sha256': sha256_bytes(str(payload['section_id']).encode('utf-8')), 'source_id_sha256': sha256_bytes(str(payload['source_id']).encode('utf-8')), 'article_id_sha256': sha256_bytes(str(article_id).encode('utf-8')) if article_id is not None else None, 'text_sha256': payload['text_sha256'], 'payload_identity_sha256': canonical_sha256(payload)}

def _validate_workflow(workflow: Mapping[str, Any]) -> dict[str, Any]:
    required = {'repository', 'workflow_name', 'run_id', 'run_attempt', 'head_sha', 'environment', 'query_id', 'evidence_mode'}
    _strict_keys(workflow, label='workflow identity', required=required)
    if workflow.get('repository') != 'danielcanfly/knowledge-engine':
        raise _failure('M26-PA2-070', 'workflow repository identity drift')
    if workflow.get('environment') != 'm23-r3-diagnostic':
        raise _failure('M26-PA2-071', 'workflow environment identity drift')
    if workflow.get('evidence_mode') != 'live_read_only':
        raise _failure('M26-PA2-072', 'workflow is not an exact live read-only run')
    if not isinstance(workflow.get('head_sha'), str) or not SAFE_HEX_40.fullmatch(workflow['head_sha']):
        raise _failure('M26-PA2-073', 'workflow head SHA is invalid')
    if not all((isinstance(workflow.get(key), str) and 0 < len(workflow[key]) <= 256 for key in ('workflow_name', 'run_id', 'run_attempt', 'query_id'))):
        raise _failure('M26-PA2-074', 'workflow identity value is invalid')
    return dict(workflow)

def _receipt_with_digest(value: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    candidate['self_sha256'] = ''
    result = dict(value)
    result['self_sha256'] = canonical_sha256(candidate)
    return result

def verify_receipt(root: Path, receipt: Mapping[str, Any]) -> None:
    schema = load_json(root / RECEIPT_SCHEMA_PATH)
    _validate_schema(receipt, schema, 'PA.2 receipt')
    verify_self_digest(receipt, 'PA.2 receipt')

def verify_failure_receipt(root: Path, receipt: Mapping[str, Any]) -> None:
    schema = load_json(root / FAILURE_SCHEMA_PATH)
    _validate_schema(receipt, schema, 'PA.2 failure receipt')
    verify_self_digest(receipt, 'PA.2 failure receipt')

def bind_real_corpus(*, root: Path, store: ReadOnlyObjectStore, qdrant: ReadOnlyQdrantClient, generated_at: str, workflow: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_pa2_contracts(root)
    entry = load_json(root / ENTRY_PATH)
    policy = load_json(root / POLICY_PATH)
    registry = load_json(root / REGISTRY_PATH)
    identity = entry['production_identity']
    workflow_value = _validate_workflow(workflow)
    if not RFC3339_UTC.fullmatch(generated_at):
        raise _failure('M26-PA2-075', 'generated_at must be second-precision UTC')
    try:
        datetime.strptime(generated_at, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as exc:
        raise _failure('M26-PA2-076', 'generated_at is not a valid UTC timestamp') from exc
    read_only = policy['read_only']
    _assert_read_only_surface(store, label='R2 object store', expected_capabilities=frozenset(read_only['r2']['allowed_operations']), expected_credential_digest=read_only['r2']['credential_contract_sha256'])
    _assert_read_only_surface(qdrant, label='Qdrant client', expected_capabilities=frozenset(read_only['qdrant']['allowed_operations']), expected_credential_digest=read_only['qdrant']['credential_contract_sha256'])
    pointer_bytes = store.get(identity['pointer_key'])
    pointer = _validate_pointer(pointer_bytes=pointer_bytes, entry=entry)
    manifest_bytes = store.get(pointer['manifest_key'])
    manifest, artifact_count, artifact_inventory_sha256 = _validate_manifest(manifest_bytes=manifest_bytes, entry=entry, policy=policy)
    qdrant_policy = policy['qdrant']
    query_filter = _qdrant_filter(qdrant_policy['filter'])
    timeout_seconds = qdrant_policy['timeout_seconds']
    count_response = qdrant.count(collection=identity['qdrant_collection'], query_filter=query_filter, timeout_seconds=timeout_seconds)
    count_result = _validate_qdrant_envelope(count_response.payload, 'count')
    _strict_keys(count_result, label='Qdrant count result', required={'count'})
    observed_count = count_result.get('count')
    if observed_count != qdrant_policy['expected_point_count']:
        raise _failure('M26-PA2-077', 'Qdrant point count drift')
    point_ids: set[str] = set()
    section_ids: set[str] = set()
    candidates: list[tuple[str, dict[str, Any]]] = []
    pagination_trace: list[dict[str, Any]] = []
    offset: Any = None
    seen_offsets: set[str] = set()
    page_count = 0
    scroll_attempts = 0
    while True:
        if page_count >= qdrant_policy['maximum_pages']:
            raise _failure('M26-PA2-078', 'Qdrant pagination exceeded the maximum page count')
        request: dict[str, Any] = {'filter': query_filter, 'limit': qdrant_policy['page_size'], 'with_payload': qdrant_policy['with_payload'], 'with_vector': False}
        if offset is not None:
            request['offset'] = offset
        response = qdrant.scroll(collection=identity['qdrant_collection'], request=request, timeout_seconds=timeout_seconds)
        scroll_attempts += response.attempts
        result = _validate_qdrant_envelope(response.payload, 'scroll')
        _strict_keys(result, label='Qdrant scroll result', required={'points', 'next_page_offset'})
        rows = _list(result.get('points'), 'Qdrant points')
        if len(rows) > qdrant_policy['page_size']:
            raise _failure('M26-PA2-079', 'Qdrant page exceeds the bounded page size')
        next_offset = result.get('next_page_offset')
        if not rows and next_offset is not None:
            raise _failure('M26-PA2-080', 'Qdrant returned a partial empty page')
        page_count += 1
        pagination_trace.append({'page': page_count, 'request_offset_sha256': canonical_sha256(offset) if offset is not None else None, 'row_count': len(rows), 'next_offset_sha256': canonical_sha256(next_offset) if next_offset is not None else None})
        for raw_row in rows:
            row = _object(raw_row, 'Qdrant point')
            _strict_keys(row, label='Qdrant point', required={'id', 'payload'})
            if 'vector' in row:
                raise _failure('M26-PA2-081', 'Qdrant returned a vector')
            point_id = _point_id(row['id'])
            if point_id in point_ids:
                raise _failure('M26-PA2-082', 'Qdrant returned a duplicate point ID')
            point_ids.add(point_id)
            payload = _validate_payload(_object(row.get('payload'), 'Qdrant payload'), policy=policy)
            section_id = str(payload['section_id'])
            if section_id in section_ids:
                raise _failure('M26-PA2-083', 'Qdrant returned a duplicate section ID')
            section_ids.add(section_id)
            sample = _sample_entry(point_id, payload)
            rank = canonical_sha256({'point_id_sha256': sample['point_id_sha256'], 'payload_identity_sha256': sample['payload_identity_sha256'], 'sample_seed': qdrant_policy['sample_seed']})
            candidates.append((rank, sample))
        if next_offset is None:
            break
        offset_token = canonical_json_scalar(next_offset)
        if offset_token in seen_offsets:
            raise _failure('M26-PA2-084', 'Qdrant pagination offset repeated')
        seen_offsets.add(offset_token)
        offset = next_offset
    if len(point_ids) != observed_count:
        raise _failure('M26-PA2-085', 'Qdrant paginated population is incomplete')
    candidates.sort(key=lambda item: (item[0], item[1]['point_id_sha256']))
    samples = [item[1] for item in candidates[:qdrant_policy['sample_size']]]
    if len(samples) != qdrant_policy['sample_size']:
        raise _failure('M26-PA2-086', 'Qdrant deterministic sample is incomplete')
    artifact_digests = {'entry_contract_sha256': canonical_sha256(entry), 'retrieval_policy_sha256': canonical_sha256(policy), 'contract_registry_sha256': canonical_sha256(registry), 'receipt_schema_sha256': sha256_bytes((root / RECEIPT_SCHEMA_PATH).read_bytes()), 'failure_schema_sha256': sha256_bytes((root / FAILURE_SCHEMA_PATH).read_bytes())}
    receipt = _receipt_with_digest({'schema_version': 'knowledge-engine-m26-pa-2-real-corpus-receipt/v1', 'status': 'real_corpus_retrieval_binding_verified', 'generated_at': generated_at, 'workflow': workflow_value, 'release': {'pointer_key': identity['pointer_key'], 'pointer_sha256': sha256_bytes(pointer_bytes), 'release_id': identity['release_id'], 'manifest_key': identity['manifest_key'], 'manifest_sha256': sha256_bytes(manifest_bytes), 'engine_sha': identity['engine_sha'], 'source_sha': identity['source_sha'], 'foundation_sha': identity['foundation_sha'], 'admission_sha256': identity['admission_sha256'], 'artifact_count': artifact_count, 'artifact_inventory_sha256': artifact_inventory_sha256, 'counts': manifest['counts']}, 'qdrant': {'collection': identity['qdrant_collection'], 'filter_sha256': canonical_sha256(query_filter), 'expected_point_count': qdrant_policy['expected_point_count'], 'observed_point_count': observed_count, 'page_size': qdrant_policy['page_size'], 'page_count': page_count, 'sample_size': len(samples), 'sample_seed_sha256': sha256_bytes(qdrant_policy['sample_seed'].encode('utf-8')), 'pagination_trace_sha256': canonical_sha256(pagination_trace), 'point_ids_sha256': canonical_sha256(sorted(point_ids)), 'with_payload': qdrant_policy['with_payload'], 'with_vector': False, 'duplicate_point_ids': False, 'duplicate_section_ids': False}, 'sample': samples, 'authority': {'r2_read_operations': 2, 'qdrant_count_operations': 1, 'qdrant_scroll_operations': page_count, 'qdrant_transport_attempts': count_response.attempts + scroll_attempts, 'r2_write_operations': 0, 'qdrant_write_operations': 0, 'production_pointer_mutations': 0, 'provider_calls': 0, 'answer_generation_operations': 0, 'public_shadow_canary_traffic_operations': 0, 'vectors_requested': False, 'vectors_returned': False, 'raw_text_persisted': False, 'secrets_persisted': False, 'read_only_credentials_verified': True}, 'artifact_digests': artifact_digests, 'self_sha256': ''})
    verify_receipt(root, receipt)
    if validation['accepted'] is not False:
        raise _failure('M26-PA2-087', 'code-only validation cannot imply stage acceptance')
    return receipt

def canonical_json_scalar(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _failure('M26-PA2-088', 'Qdrant pagination offset is invalid')
    if isinstance(value, str) and (not value or len(value) > 256):
        raise _failure('M26-PA2-089', 'Qdrant pagination offset is invalid')
    return canonical_bytes(value).decode('utf-8')

def receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    return pretty_bytes(dict(receipt))

def build_sanitized_failure_receipt(*, root: Path, generated_at: str, workflow: Mapping[str, Any], error: Exception, operation_counts: Mapping[str, int] | None=None) -> dict[str, Any]:
    workflow_value = _validate_workflow(workflow)
    if not RFC3339_UTC.fullmatch(generated_at):
        raise _failure('M26-PA2-090', 'failure receipt generated_at is invalid')
    if isinstance(error, RealCorpusBindingError):
        code = error.code
        category = error.category
        retryable = error.retryable
        message = error.safe_message
    else:
        code = 'M26-PA2-UNEXPECTED'
        category = 'internal'
        retryable = False
        message = 'unexpected bounded read-only binding failure'
    counts = {'r2_reads': 0, 'qdrant_count_requests': 0, 'qdrant_scroll_requests': 0}
    if operation_counts is not None:
        if set(operation_counts) != set(counts) or any((not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in operation_counts.values())):
            raise _failure('M26-PA2-091', 'failure operation counts are invalid')
        counts.update(operation_counts)
    receipt = _receipt_with_digest({'schema_version': 'knowledge-engine-m26-pa-2-failure-receipt/v1', 'status': 'real_corpus_retrieval_binding_failed', 'generated_at': generated_at, 'workflow': workflow_value, 'error': {'code': code, 'category': category, 'retryable': retryable, 'message': message}, 'operation_counts': counts, 'authority': {'r2_write_operations': 0, 'qdrant_write_operations': 0, 'production_pointer_mutations': 0, 'provider_calls': 0, 'answer_generation_operations': 0, 'public_shadow_canary_traffic_operations': 0, 'raw_text_persisted': False, 'vectors_persisted': False, 'secrets_persisted': False}, 'self_sha256': ''})
    verify_failure_receipt(root, receipt)
    serialized = receipt_bytes(receipt).decode('utf-8').lower()
    if any((pattern.search(serialized) for pattern in SECRET_VALUE_PATTERNS)):
        raise _failure('M26-PA2-092', 'failure receipt contains secret-like material')
    return receipt
