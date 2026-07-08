from __future__ import annotations

import json
import re
import stat
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .intake_v1 import IntakeFailure, canonical_json_bytes
from .media_bundle import FileIdentity, _read_regular_file, _verify_identity, canonical_relative_path
from .storage import sha256_bytes

MANIFEST_SCHEMA = "database-metadata-manifest/v1"
METADATA_SCHEMA = "database-metadata-export/v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_METADATA_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_SCHEMAS = 1_000
DEFAULT_MAX_RELATIONS = 20_000
DEFAULT_MAX_COLUMNS = 200_000
DEFAULT_MAX_CHILD_OBJECTS = 500_000
HEX64_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.+/-]{1,128}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$-]{0,127}$")
TYPE_RE = re.compile(r"^[A-Za-z0-9_ .(),\[\]-]{1,128}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9_.+:-]{1,128}$")
ENGINES = {"postgresql", "mysql", "sqlite", "sqlserver", "generic"}
RELATION_KINDS = {"table", "partitioned_table", "foreign_table"}
CONSTRAINT_TYPES = {"primary_key", "unique", "foreign_key", "check"}
INDEX_METHODS = {"btree", "hash", "gist", "spgist", "gin", "brin", "clustered", "nonclustered", "generic"}
PRIVILEGES = {
    "select",
    "insert",
    "update",
    "delete",
    "truncate",
    "references",
    "trigger",
    "usage",
    "execute",
    "create",
    "alter",
    "drop",
}
RLS_COMMANDS = {"all", "select", "insert", "update", "delete"}
POLICY_TYPES = {"public", "authenticated", "principal_set", "restricted", "unresolved"}
OBSERVATION_SOURCES = {"observed", "operator_asserted", "inherited", "unresolved"}
FORBIDDEN_FIELD_NAMES = {
    "rows",
    "row_count",
    "estimated_rows",
    "sample",
    "sample_value",
    "sample_values",
    "values",
    "query",
    "query_output",
    "sql",
    "ddl",
    "definition",
    "body",
    "function_body",
    "view_definition",
    "connection_string",
    "connection_uri",
    "host",
    "hostname",
    "port",
    "username",
    "password",
    "token",
    "certificate",
    "environment",
}


@dataclass(frozen=True)
class DatabaseAccess:
    policy_type: str
    principal_hashes: tuple[str, ...]
    observation_source: str
    native_evidence_sha256: str | None

    @property
    def minimum_audience(self) -> str:
        return {
            "public": "public",
            "authenticated": "internal",
            "principal_set": "confidential",
            "restricted": "restricted",
            "unresolved": "restricted",
        }[self.policy_type]

    @property
    def digest(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "policy_type": self.policy_type,
                    "principal_hashes": list(self.principal_hashes),
                    "observation_source": self.observation_source,
                    "native_evidence_sha256": self.native_evidence_sha256,
                }
            )
        )


@dataclass(frozen=True)
class DatabaseManifest:
    source_uri_sha256: str
    database_id_sha256: str
    database_name_sha256: str
    engine: str
    engine_version: str
    migration_head_sha256: str | None
    collected_at: str
    metadata_path: str
    metadata_sha256: str
    metadata_byte_size: int
    collector_tool: str
    collector_version: str
    access: DatabaseAccess
    manifest_sha256: str


@dataclass(frozen=True)
class DatabaseMetadata:
    schemas: tuple[dict[str, Any], ...]
    tables: tuple[dict[str, Any], ...]
    views: tuple[dict[str, Any], ...]
    canonical_bytes: bytes

    @property
    def counts(self) -> dict[str, int]:
        columns = sum(len(item["columns"]) for item in self.tables) + sum(
            len(item["columns"]) for item in self.views
        )
        constraints = sum(len(item["constraints"]) for item in self.tables)
        indexes = sum(len(item["indexes"]) for item in self.tables)
        grants = sum(len(item["grants"]) for item in self.tables) + sum(
            len(item["grants"]) for item in self.views
        )
        policies = sum(len(item["rls_policies"]) for item in self.tables)
        dependencies = sum(len(item["dependencies"]) for item in self.views)
        return {
            "schemas": len(self.schemas),
            "tables": len(self.tables),
            "views": len(self.views),
            "columns": columns,
            "constraints": constraints,
            "indexes": indexes,
            "grants": grants,
            "rls_policies": policies,
            "dependencies": dependencies,
        }


@dataclass(frozen=True)
class DatabaseBundle:
    bundle_root: Path
    bundle_identity: FileIdentity
    manifest_identity: FileIdentity
    metadata_identity: FileIdentity
    manifest_bytes: bytes
    metadata_bytes: bytes
    manifest: DatabaseManifest
    metadata: DatabaseMetadata


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    extras = set(value) - expected
    if extras & FORBIDDEN_FIELD_NAMES:
        raise IntakeFailure(
            "DATABASE_CONTENT_FIELD_FORBIDDEN",
            "safety_gate",
            f"{field} contains row, SQL, connection, or credential fields",
        )
    if set(value) != expected:
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} fields are invalid",
        )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} must be an object",
        )
    return value


def _list(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise IntakeFailure(
            "DATABASE_METADATA_LIMIT",
            "safety_gate",
            f"{field} count exceeds policy",
        )
    return value


def _string(
    value: Any,
    field: str,
    *,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 4096,
) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} is invalid",
        )
    if any(ord(char) < 32 for char in value):
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} contains controls",
        )
    normalized = unicodedata.normalize("NFC", value)
    if pattern is not None and pattern.fullmatch(normalized) is None:
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} has invalid syntax",
        )
    return normalized


def _nullable_hash(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field, pattern=HEX64_RE)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} must be boolean",
        )
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise IntakeFailure(
            "DATABASE_METADATA_SCHEMA_INVALID",
            "safety_gate",
            f"{field} is outside policy",
        )
    return value


def _utc(value: Any, field: str) -> str:
    text = _string(value, field, maximum=128)
    if not text.endswith("Z"):
        raise IntakeFailure("DATABASE_TIMESTAMP_INVALID", "safety_gate", f"{field} must be UTC")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise IntakeFailure("DATABASE_TIMESTAMP_INVALID", "safety_gate", f"{field} is invalid") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise IntakeFailure("DATABASE_TIMESTAMP_INVALID", "safety_gate", f"{field} must be UTC")
    return text


def _parse_access(value: Any) -> DatabaseAccess:
    item = _mapping(value, "access")
    _exact_keys(
        item,
        {"policy_type", "principal_hashes", "observation_source", "native_evidence_sha256"},
        "access",
    )
    policy_type = _string(item["policy_type"], "access.policy_type", maximum=64)
    observation = _string(item["observation_source"], "access.observation_source", maximum=64)
    if policy_type not in POLICY_TYPES or observation not in OBSERVATION_SOURCES:
        raise IntakeFailure("DATABASE_ACL_INVALID", "safety_gate", "database ACL is invalid")
    principals = tuple(
        sorted(
            _string(principal, "access.principal_hash", pattern=HEX64_RE)
            for principal in _list(item["principal_hashes"], "access.principal_hashes", 20_000)
        )
    )
    if len(set(principals)) != len(principals):
        raise IntakeFailure("DATABASE_ACL_INVALID", "safety_gate", "database ACL principals duplicate")
    native = item["native_evidence_sha256"]
    if policy_type == "unresolved" or observation == "unresolved":
        if policy_type != "unresolved" or observation != "unresolved" or principals or native is not None:
            raise IntakeFailure("DATABASE_ACL_INVALID", "safety_gate", "unresolved ACL is malformed")
        native_hash = None
    else:
        native_hash = _string(native, "access.native_evidence_sha256", pattern=HEX64_RE)
        if policy_type == "public" and principals:
            raise IntakeFailure("DATABASE_ACL_INVALID", "safety_gate", "public ACL cannot list principals")
        if policy_type in {"authenticated", "principal_set"} and not principals:
            raise IntakeFailure("DATABASE_ACL_INVALID", "safety_gate", "database ACL needs principals")
    return DatabaseAccess(policy_type, principals, observation, native_hash)


def parse_manifest(data: bytes, *, max_metadata_bytes: int) -> DatabaseManifest:
    if len(data) > MAX_MANIFEST_BYTES:
        raise IntakeFailure("DATABASE_MANIFEST_TOO_LARGE", "safety_gate", "manifest exceeds policy")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntakeFailure("DATABASE_MANIFEST_INVALID", "safety_gate", "manifest JSON is invalid") from exc
    root = _mapping(payload, "manifest")
    _exact_keys(
        root,
        {"schema_version", "source_uri_sha256", "database", "export", "collector", "access"},
        "manifest",
    )
    if root["schema_version"] != MANIFEST_SCHEMA:
        raise IntakeFailure(
            "DATABASE_MANIFEST_VERSION_UNSUPPORTED",
            "safety_gate",
            "manifest version unsupported",
        )
    source_hash = _string(root["source_uri_sha256"], "source_uri_sha256", pattern=HEX64_RE)
    database = _mapping(root["database"], "database")
    _exact_keys(
        database,
        {
            "database_id_sha256",
            "database_name_sha256",
            "engine",
            "engine_version",
            "migration_head_sha256",
        },
        "database",
    )
    database_id = _string(database["database_id_sha256"], "database.database_id_sha256", pattern=HEX64_RE)
    database_name = _string(database["database_name_sha256"], "database.database_name_sha256", pattern=HEX64_RE)
    engine = _string(database["engine"], "database.engine", maximum=32)
    if engine not in ENGINES:
        raise IntakeFailure("DATABASE_ENGINE_UNSUPPORTED", "safety_gate", "database engine unsupported")
    engine_version = _string(database["engine_version"], "database.engine_version", pattern=VERSION_RE)
    migration_head = _nullable_hash(database["migration_head_sha256"], "database.migration_head_sha256")

    export = _mapping(root["export"], "export")
    _exact_keys(export, {"path", "sha256", "byte_size", "collected_at"}, "export")
    metadata_path = canonical_relative_path(_string(export["path"], "export.path", maximum=512))
    metadata_hash = _string(export["sha256"], "export.sha256", pattern=HEX64_RE)
    metadata_size = _integer(export["byte_size"], "export.byte_size", 1, max_metadata_bytes)
    collected_at = _utc(export["collected_at"], "export.collected_at")

    collector = _mapping(root["collector"], "collector")
    _exact_keys(collector, {"tool", "version"}, "collector")
    collector_tool = _string(collector["tool"], "collector.tool", pattern=SAFE_ID_RE)
    collector_version = _string(collector["version"], "collector.version", pattern=VERSION_RE)
    access = _parse_access(root["access"])
    return DatabaseManifest(
        source_uri_sha256=source_hash,
        database_id_sha256=database_id,
        database_name_sha256=database_name,
        engine=engine,
        engine_version=engine_version,
        migration_head_sha256=migration_head,
        collected_at=collected_at,
        metadata_path=metadata_path,
        metadata_sha256=metadata_hash,
        metadata_byte_size=metadata_size,
        collector_tool=collector_tool,
        collector_version=collector_version,
        access=access,
        manifest_sha256=sha256_bytes(data),
    )


def _parse_column(value: Any, field: str, ordinal_max: int) -> dict[str, Any]:
    item = _mapping(value, field)
    _exact_keys(
        item,
        {
            "name",
            "ordinal",
            "data_type",
            "nullable",
            "generated",
            "identity",
            "default_expression_sha256",
        },
        field,
    )
    return {
        "name": _string(item["name"], f"{field}.name", pattern=NAME_RE),
        "ordinal": _integer(item["ordinal"], f"{field}.ordinal", 1, ordinal_max),
        "data_type": _string(item["data_type"], f"{field}.data_type", pattern=TYPE_RE),
        "nullable": _boolean(item["nullable"], f"{field}.nullable"),
        "generated": _boolean(item["generated"], f"{field}.generated"),
        "identity": _boolean(item["identity"], f"{field}.identity"),
        "default_expression_sha256": _nullable_hash(
            item["default_expression_sha256"],
            f"{field}.default_expression_sha256",
        ),
    }


def _parse_grants(value: Any, field: str) -> tuple[dict[str, Any], ...]:
    grants: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for index, raw in enumerate(_list(value, field, DEFAULT_MAX_CHILD_OBJECTS)):
        item = _mapping(raw, f"{field}[{index}]")
        _exact_keys(item, {"principal_sha256", "privileges", "grantable"}, f"{field}[{index}]")
        principal = _string(item["principal_sha256"], f"{field}[{index}].principal_sha256", pattern=HEX64_RE)
        privileges = tuple(
            sorted(
                _string(privilege, f"{field}[{index}].privilege", maximum=32)
                for privilege in _list(item["privileges"], f"{field}[{index}].privileges", 32)
            )
        )
        if not privileges or len(set(privileges)) != len(privileges) or any(p not in PRIVILEGES for p in privileges):
            raise IntakeFailure("DATABASE_GRANT_INVALID", "safety_gate", "grant privileges are invalid")
        identity = (principal, privileges)
        if identity in seen:
            raise IntakeFailure("DATABASE_GRANT_DUPLICATE", "safety_gate", "grant is duplicated")
        seen.add(identity)
        grants.append(
            {
                "principal_sha256": principal,
                "privileges": list(privileges),
                "grantable": _boolean(item["grantable"], f"{field}[{index}].grantable"),
            }
        )
    return tuple(sorted(grants, key=lambda item: (item["principal_sha256"], item["privileges"])))


def _parse_table(
    value: Any,
    index: int,
    *,
    max_columns: int,
    max_children: int,
) -> dict[str, Any]:
    field = f"tables[{index}]"
    item = _mapping(value, field)
    _exact_keys(
        item,
        {
            "schema",
            "name",
            "kind",
            "owner_principal_sha256",
            "rls_enabled",
            "rls_forced",
            "columns",
            "constraints",
            "indexes",
            "grants",
            "rls_policies",
        },
        field,
    )
    schema = _string(item["schema"], f"{field}.schema", pattern=NAME_RE)
    name = _string(item["name"], f"{field}.name", pattern=NAME_RE)
    kind = _string(item["kind"], f"{field}.kind", maximum=32)
    if kind not in RELATION_KINDS:
        raise IntakeFailure("DATABASE_RELATION_KIND_INVALID", "safety_gate", "table kind is invalid")
    owner = _nullable_hash(item["owner_principal_sha256"], f"{field}.owner_principal_sha256")
    columns_raw = _list(item["columns"], f"{field}.columns", max_columns)
    if not columns_raw:
        raise IntakeFailure("DATABASE_COLUMN_INVALID", "safety_gate", "table requires columns")
    columns = tuple(_parse_column(raw, f"{field}.columns[{i}]", max_columns) for i, raw in enumerate(columns_raw))
    column_names = [column["name"] for column in columns]
    if len(set(column_names)) != len(column_names):
        raise IntakeFailure("DATABASE_COLUMN_DUPLICATE", "safety_gate", "column name is duplicated")
    if sorted(column["ordinal"] for column in columns) != list(range(1, len(columns) + 1)):
        raise IntakeFailure("DATABASE_COLUMN_ORDINAL_INVALID", "safety_gate", "column ordinals must be contiguous")
    rls_enabled = _boolean(item["rls_enabled"], f"{field}.rls_enabled")
    rls_forced = _boolean(item["rls_forced"], f"{field}.rls_forced")
    if rls_forced and not rls_enabled:
        raise IntakeFailure("DATABASE_RLS_INVALID", "safety_gate", "forced RLS requires enabled RLS")

    constraints: list[dict[str, Any]] = []
    constraint_names: set[str] = set()
    for child_index, raw in enumerate(_list(item["constraints"], f"{field}.constraints", max_children)):
        child_field = f"{field}.constraints[{child_index}]"
        child = _mapping(raw, child_field)
        _exact_keys(
            child,
            {
                "name",
                "type",
                "columns",
                "referenced_schema",
                "referenced_table",
                "referenced_columns",
                "deferrable",
                "initially_deferred",
                "expression_sha256",
            },
            child_field,
        )
        constraint_name = _string(child["name"], f"{child_field}.name", pattern=NAME_RE)
        if constraint_name in constraint_names:
            raise IntakeFailure("DATABASE_CONSTRAINT_DUPLICATE", "safety_gate", "constraint is duplicated")
        constraint_names.add(constraint_name)
        constraint_type = _string(child["type"], f"{child_field}.type", maximum=32)
        if constraint_type not in CONSTRAINT_TYPES:
            raise IntakeFailure("DATABASE_CONSTRAINT_INVALID", "safety_gate", "constraint type is invalid")
        local_columns = tuple(
            _string(column, f"{child_field}.column", pattern=NAME_RE)
            for column in _list(child["columns"], f"{child_field}.columns", max_columns)
        )
        if not local_columns or len(set(local_columns)) != len(local_columns) or any(c not in column_names for c in local_columns):
            raise IntakeFailure("DATABASE_CONSTRAINT_INVALID", "safety_gate", "constraint columns are invalid")
        referenced_schema = child["referenced_schema"]
        referenced_table = child["referenced_table"]
        referenced_columns_raw = child["referenced_columns"]
        expression = child["expression_sha256"]
        if constraint_type == "foreign_key":
            referenced_schema = _string(referenced_schema, f"{child_field}.referenced_schema", pattern=NAME_RE)
            referenced_table = _string(referenced_table, f"{child_field}.referenced_table", pattern=NAME_RE)
            referenced_columns = tuple(
                _string(column, f"{child_field}.referenced_column", pattern=NAME_RE)
                for column in _list(referenced_columns_raw, f"{child_field}.referenced_columns", max_columns)
            )
            if len(referenced_columns) != len(local_columns):
                raise IntakeFailure("DATABASE_FOREIGN_KEY_INVALID", "safety_gate", "foreign-key columns differ")
            if expression is not None:
                raise IntakeFailure("DATABASE_FOREIGN_KEY_INVALID", "safety_gate", "foreign key cannot carry expression")
            expression_hash = None
        elif constraint_type == "check":
            if referenced_schema is not None or referenced_table is not None or referenced_columns_raw != []:
                raise IntakeFailure("DATABASE_CONSTRAINT_INVALID", "safety_gate", "check reference fields must be empty")
            referenced_columns = ()
            expression_hash = _string(expression, f"{child_field}.expression_sha256", pattern=HEX64_RE)
        else:
            if referenced_schema is not None or referenced_table is not None or referenced_columns_raw != [] or expression is not None:
                raise IntakeFailure("DATABASE_CONSTRAINT_INVALID", "safety_gate", "constraint fields are inconsistent")
            referenced_columns = ()
            expression_hash = None
        constraints.append(
            {
                "name": constraint_name,
                "type": constraint_type,
                "columns": list(local_columns),
                "referenced_schema": referenced_schema,
                "referenced_table": referenced_table,
                "referenced_columns": list(referenced_columns),
                "deferrable": _boolean(child["deferrable"], f"{child_field}.deferrable"),
                "initially_deferred": _boolean(child["initially_deferred"], f"{child_field}.initially_deferred"),
                "expression_sha256": expression_hash,
            }
        )

    indexes: list[dict[str, Any]] = []
    index_names: set[str] = set()
    for child_index, raw in enumerate(_list(item["indexes"], f"{field}.indexes", max_children)):
        child_field = f"{field}.indexes[{child_index}]"
        child = _mapping(raw, child_field)
        _exact_keys(
            child,
            {"name", "unique", "primary", "method", "columns", "predicate_sha256", "expression_sha256"},
            child_field,
        )
        index_name = _string(child["name"], f"{child_field}.name", pattern=NAME_RE)
        if index_name in index_names:
            raise IntakeFailure("DATABASE_INDEX_DUPLICATE", "safety_gate", "index is duplicated")
        index_names.add(index_name)
        method = _string(child["method"], f"{child_field}.method", maximum=32)
        if method not in INDEX_METHODS:
            raise IntakeFailure("DATABASE_INDEX_INVALID", "safety_gate", "index method is invalid")
        index_columns = tuple(
            _string(column, f"{child_field}.column", pattern=NAME_RE)
            for column in _list(child["columns"], f"{child_field}.columns", max_columns)
        )
        expression_hash = _nullable_hash(child["expression_sha256"], f"{child_field}.expression_sha256")
        if not index_columns and expression_hash is None:
            raise IntakeFailure("DATABASE_INDEX_INVALID", "safety_gate", "index needs columns or expression")
        if len(set(index_columns)) != len(index_columns) or any(c not in column_names for c in index_columns):
            raise IntakeFailure("DATABASE_INDEX_INVALID", "safety_gate", "index columns are invalid")
        primary = _boolean(child["primary"], f"{child_field}.primary")
        unique = _boolean(child["unique"], f"{child_field}.unique")
        if primary and not unique:
            raise IntakeFailure("DATABASE_INDEX_INVALID", "safety_gate", "primary index must be unique")
        indexes.append(
            {
                "name": index_name,
                "unique": unique,
                "primary": primary,
                "method": method,
                "columns": list(index_columns),
                "predicate_sha256": _nullable_hash(child["predicate_sha256"], f"{child_field}.predicate_sha256"),
                "expression_sha256": expression_hash,
            }
        )

    policies: list[dict[str, Any]] = []
    policy_names: set[str] = set()
    for child_index, raw in enumerate(_list(item["rls_policies"], f"{field}.rls_policies", max_children)):
        child_field = f"{field}.rls_policies[{child_index}]"
        child = _mapping(raw, child_field)
        _exact_keys(
            child,
            {
                "name",
                "command",
                "role_principal_hashes",
                "permissive",
                "using_expression_sha256",
                "check_expression_sha256",
            },
            child_field,
        )
        if not rls_enabled:
            raise IntakeFailure("DATABASE_RLS_INVALID", "safety_gate", "RLS policies require enabled RLS")
        policy_name = _string(child["name"], f"{child_field}.name", pattern=NAME_RE)
        if policy_name in policy_names:
            raise IntakeFailure("DATABASE_RLS_POLICY_DUPLICATE", "safety_gate", "RLS policy is duplicated")
        policy_names.add(policy_name)
        command = _string(child["command"], f"{child_field}.command", maximum=16)
        if command not in RLS_COMMANDS:
            raise IntakeFailure("DATABASE_RLS_INVALID", "safety_gate", "RLS command is invalid")
        roles = tuple(
            sorted(
                _string(role, f"{child_field}.role", pattern=HEX64_RE)
                for role in _list(child["role_principal_hashes"], f"{child_field}.roles", 20_000)
            )
        )
        if len(set(roles)) != len(roles):
            raise IntakeFailure("DATABASE_RLS_INVALID", "safety_gate", "RLS role is duplicated")
        using_hash = _nullable_hash(child["using_expression_sha256"], f"{child_field}.using_expression_sha256")
        check_hash = _nullable_hash(child["check_expression_sha256"], f"{child_field}.check_expression_sha256")
        if using_hash is None and check_hash is None:
            raise IntakeFailure("DATABASE_RLS_INVALID", "safety_gate", "RLS policy requires expression evidence")
        policies.append(
            {
                "name": policy_name,
                "command": command,
                "role_principal_hashes": list(roles),
                "permissive": _boolean(child["permissive"], f"{child_field}.permissive"),
                "using_expression_sha256": using_hash,
                "check_expression_sha256": check_hash,
            }
        )

    return {
        "schema": schema,
        "name": name,
        "kind": kind,
        "owner_principal_sha256": owner,
        "rls_enabled": rls_enabled,
        "rls_forced": rls_forced,
        "columns": tuple(sorted(columns, key=lambda column: column["ordinal"])),
        "constraints": tuple(sorted(constraints, key=lambda constraint: constraint["name"])),
        "indexes": tuple(sorted(indexes, key=lambda index: index["name"])),
        "grants": _parse_grants(item["grants"], f"{field}.grants"),
        "rls_policies": tuple(sorted(policies, key=lambda policy: policy["name"])),
    }


def _parse_view(value: Any, index: int, *, max_columns: int, max_children: int) -> dict[str, Any]:
    field = f"views[{index}]"
    item = _mapping(value, field)
    _exact_keys(
        item,
        {"schema", "name", "materialized", "owner_principal_sha256", "columns", "definition_sha256", "dependencies", "grants"},
        field,
    )
    columns_raw = _list(item["columns"], f"{field}.columns", max_columns)
    if not columns_raw:
        raise IntakeFailure("DATABASE_COLUMN_INVALID", "safety_gate", "view requires columns")
    columns = tuple(_parse_column(raw, f"{field}.columns[{i}]", max_columns) for i, raw in enumerate(columns_raw))
    names = [column["name"] for column in columns]
    if len(set(names)) != len(names) or sorted(column["ordinal"] for column in columns) != list(range(1, len(columns) + 1)):
        raise IntakeFailure("DATABASE_COLUMN_ORDINAL_INVALID", "safety_gate", "view columns are invalid")
    dependencies: list[dict[str, str]] = []
    seen_dependencies: set[tuple[str, str, str]] = set()
    for child_index, raw in enumerate(_list(item["dependencies"], f"{field}.dependencies", max_children)):
        child_field = f"{field}.dependencies[{child_index}]"
        child = _mapping(raw, child_field)
        _exact_keys(child, {"schema", "name", "kind"}, child_field)
        dependency = (
            _string(child["schema"], f"{child_field}.schema", pattern=NAME_RE),
            _string(child["name"], f"{child_field}.name", pattern=NAME_RE),
            _string(child["kind"], f"{child_field}.kind", maximum=16),
        )
        if dependency[2] not in {"table", "view"} or dependency in seen_dependencies:
            raise IntakeFailure("DATABASE_DEPENDENCY_INVALID", "safety_gate", "view dependency is invalid")
        seen_dependencies.add(dependency)
        dependencies.append({"schema": dependency[0], "name": dependency[1], "kind": dependency[2]})
    return {
        "schema": _string(item["schema"], f"{field}.schema", pattern=NAME_RE),
        "name": _string(item["name"], f"{field}.name", pattern=NAME_RE),
        "materialized": _boolean(item["materialized"], f"{field}.materialized"),
        "owner_principal_sha256": _nullable_hash(item["owner_principal_sha256"], f"{field}.owner_principal_sha256"),
        "columns": tuple(sorted(columns, key=lambda column: column["ordinal"])),
        "definition_sha256": _string(item["definition_sha256"], f"{field}.definition_sha256", pattern=HEX64_RE),
        "dependencies": tuple(sorted(dependencies, key=lambda dependency: (dependency["schema"], dependency["name"], dependency["kind"]))),
        "grants": _parse_grants(item["grants"], f"{field}.grants"),
    }


def parse_metadata(
    data: bytes,
    *,
    max_schemas: int,
    max_relations: int,
    max_columns: int,
    max_children: int,
) -> DatabaseMetadata:
    if b"\x00" in data:
        raise IntakeFailure("DATABASE_METADATA_BINARY", "safety_gate", "metadata contains NUL bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntakeFailure("DATABASE_METADATA_INVALID", "safety_gate", "metadata JSON is invalid") from exc
    root = _mapping(payload, "metadata")
    _exact_keys(root, {"schema_version", "schemas", "tables", "views"}, "metadata")
    if root["schema_version"] != METADATA_SCHEMA:
        raise IntakeFailure(
            "DATABASE_METADATA_VERSION_UNSUPPORTED",
            "safety_gate",
            "metadata version unsupported",
        )
    schemas: list[dict[str, Any]] = []
    schema_names: set[str] = set()
    for index, raw in enumerate(_list(root["schemas"], "schemas", max_schemas)):
        field = f"schemas[{index}]"
        item = _mapping(raw, field)
        _exact_keys(item, {"name", "owner_principal_sha256"}, field)
        name = _string(item["name"], f"{field}.name", pattern=NAME_RE)
        if name in schema_names:
            raise IntakeFailure("DATABASE_SCHEMA_DUPLICATE", "safety_gate", "schema is duplicated")
        schema_names.add(name)
        schemas.append(
            {
                "name": name,
                "owner_principal_sha256": _nullable_hash(item["owner_principal_sha256"], f"{field}.owner_principal_sha256"),
            }
        )
    if not schemas:
        raise IntakeFailure("DATABASE_SCHEMA_INVALID", "safety_gate", "metadata requires schemas")

    table_values = _list(root["tables"], "tables", max_relations)
    view_values = _list(root["views"], "views", max_relations)
    if len(table_values) + len(view_values) > max_relations:
        raise IntakeFailure("DATABASE_METADATA_LIMIT", "safety_gate", "relation count exceeds policy")
    tables = tuple(
        _parse_table(raw, index, max_columns=max_columns, max_children=max_children)
        for index, raw in enumerate(table_values)
    )
    views = tuple(
        _parse_view(raw, index, max_columns=max_columns, max_children=max_children)
        for index, raw in enumerate(view_values)
    )
    relation_ids: set[tuple[str, str]] = set()
    table_map: dict[tuple[str, str], dict[str, Any]] = {}
    view_map: dict[tuple[str, str], dict[str, Any]] = {}
    for relation in tables:
        identity = (relation["schema"], relation["name"])
        if relation["schema"] not in schema_names or identity in relation_ids:
            raise IntakeFailure("DATABASE_RELATION_INVALID", "safety_gate", "table identity is invalid")
        relation_ids.add(identity)
        table_map[identity] = relation
    for relation in views:
        identity = (relation["schema"], relation["name"])
        if relation["schema"] not in schema_names or identity in relation_ids:
            raise IntakeFailure("DATABASE_RELATION_INVALID", "safety_gate", "view identity is invalid")
        relation_ids.add(identity)
        view_map[identity] = relation

    for table in tables:
        for constraint in table["constraints"]:
            if constraint["type"] != "foreign_key":
                continue
            target_id = (constraint["referenced_schema"], constraint["referenced_table"])
            target = table_map.get(target_id)
            if target is None:
                raise IntakeFailure("DATABASE_FOREIGN_KEY_REFERENCE_INVALID", "safety_gate", "foreign key target is missing")
            target_columns = {column["name"] for column in target["columns"]}
            if any(column not in target_columns for column in constraint["referenced_columns"]):
                raise IntakeFailure("DATABASE_FOREIGN_KEY_REFERENCE_INVALID", "safety_gate", "foreign key target column is missing")
    for view in views:
        for dependency in view["dependencies"]:
            target_id = (dependency["schema"], dependency["name"])
            expected = table_map if dependency["kind"] == "table" else view_map
            if target_id not in expected or target_id == (view["schema"], view["name"]):
                raise IntakeFailure("DATABASE_DEPENDENCY_REFERENCE_INVALID", "safety_gate", "view dependency is missing")

    canonical = {
        "schema_version": METADATA_SCHEMA,
        "schemas": sorted(schemas, key=lambda item: item["name"]),
        "tables": sorted(tables, key=lambda item: (item["schema"], item["name"])),
        "views": sorted(views, key=lambda item: (item["schema"], item["name"])),
    }
    canonical_bytes = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    metadata = DatabaseMetadata(
        schemas=tuple(canonical["schemas"]),
        tables=tuple(canonical["tables"]),
        views=tuple(canonical["views"]),
        canonical_bytes=canonical_bytes,
    )
    counts = metadata.counts
    if counts["columns"] > max_columns or sum(
        counts[key]
        for key in ("constraints", "indexes", "grants", "rls_policies", "dependencies")
    ) > max_children:
        raise IntakeFailure("DATABASE_METADATA_LIMIT", "safety_gate", "metadata child count exceeds policy")
    return metadata


def _translate_bundle_failure(failure: IntakeFailure) -> IntakeFailure:
    if failure.code.startswith("MEDIA_BUNDLE_"):
        return IntakeFailure(
            failure.code.replace("MEDIA_BUNDLE_", "DATABASE_BUNDLE_", 1),
            failure.stage,
            failure.safe_message,
            transient=failure.transient,
            safe_context=failure.safe_context,
        )
    return failure


def _safe_read(path: Path, max_bytes: int) -> tuple[bytes, FileIdentity]:
    try:
        return _read_regular_file(path, max_bytes=max_bytes)
    except IntakeFailure as failure:
        raise _translate_bundle_failure(failure) from failure


def _safe_verify(identity: FileIdentity) -> None:
    try:
        _verify_identity(identity)
    except IntakeFailure as failure:
        raise _translate_bundle_failure(failure) from failure


def _reject_symlink_components(allowed_root: Path, candidate: Path) -> None:
    absolute = candidate if candidate.is_absolute() else allowed_root / candidate
    try:
        relative = absolute.relative_to(allowed_root)
    except ValueError as exc:
        raise IntakeFailure("PATH_ESCAPE", "discover", "database bundle escapes allowed root") from exc
    current = allowed_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise IntakeFailure("SYMLINK_ESCAPE", "discover", "database bundle path contains symlink")


class LocalDatabaseBundleReader:
    def __init__(self, allowed_root: Path) -> None:
        try:
            self.allowed_root = allowed_root.resolve(strict=True)
        except FileNotFoundError as exc:
            raise IntakeFailure("ALLOWED_ROOT_NOT_FOUND", "request", "allowed root not found") from exc
        if not self.allowed_root.is_dir():
            raise IntakeFailure("INVALID_ALLOWED_ROOT", "request", "allowed root must be a directory")

    def _root(self, locator: str) -> Path:
        candidate = Path(locator)
        if not candidate.is_absolute():
            candidate = self.allowed_root / candidate
        _reject_symlink_components(self.allowed_root, candidate)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.allowed_root)
        except FileNotFoundError as exc:
            raise IntakeFailure("DATABASE_BUNDLE_NOT_FOUND", "discover", "database bundle not found") from exc
        except ValueError as exc:
            raise IntakeFailure("PATH_ESCAPE", "discover", "database bundle escapes allowed root") from exc
        info = resolved.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise IntakeFailure("DATABASE_BUNDLE_INVALID", "discover", "database bundle must be a directory")
        return resolved

    def read(
        self,
        locator: str,
        *,
        max_metadata_bytes: int,
        max_schemas: int,
        max_relations: int,
        max_columns: int,
        max_children: int,
    ) -> DatabaseBundle:
        root = self._root(locator)
        root_info = root.stat(follow_symlinks=False)
        root_identity = FileIdentity(root, root_info.st_dev, root_info.st_ino, root_info.st_size, root_info.st_mtime_ns)
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink():
            raise IntakeFailure("SYMLINK_ESCAPE", "discover", "manifest must not be a symlink")
        manifest_bytes, manifest_identity = _safe_read(manifest_path, MAX_MANIFEST_BYTES)
        manifest = parse_manifest(manifest_bytes, max_metadata_bytes=max_metadata_bytes)
        metadata_path = root.joinpath(*PurePosixPath(manifest.metadata_path).parts)
        if metadata_path == manifest_path:
            raise IntakeFailure("DATABASE_BUNDLE_PATH_COLLISION", "safety_gate", "bundle paths collide")
        _reject_symlink_components(self.allowed_root, metadata_path)
        metadata_bytes, metadata_identity = _safe_read(metadata_path, max_metadata_bytes)
        if len(metadata_bytes) != manifest.metadata_byte_size or sha256_bytes(metadata_bytes) != manifest.metadata_sha256:
            raise IntakeFailure(
                "DATABASE_METADATA_HASH_MISMATCH",
                "safety_gate",
                "metadata bytes differ from manifest",
            )
        metadata = parse_metadata(
            metadata_bytes,
            max_schemas=max_schemas,
            max_relations=max_relations,
            max_columns=max_columns,
            max_children=max_children,
        )
        for identity in (root_identity, manifest_identity, metadata_identity):
            _safe_verify(identity)
        return DatabaseBundle(
            bundle_root=root,
            bundle_identity=root_identity,
            manifest_identity=manifest_identity,
            metadata_identity=metadata_identity,
            manifest_bytes=manifest_bytes,
            metadata_bytes=metadata_bytes,
            manifest=manifest,
            metadata=metadata,
        )


def _hash_short(value: str | None) -> str:
    return "none" if value is None else value[:12]


def render_derivative(manifest: DatabaseManifest, metadata: DatabaseMetadata) -> bytes:
    counts = metadata.counts
    lines = [
        "# Database Metadata Export",
        "",
        "## Export Evidence",
        "",
        f"- Engine: `{manifest.engine}`",
        f"- Engine version: `{manifest.engine_version}`",
        f"- Collected at: `{manifest.collected_at}`",
        f"- Migration head SHA-256: `{manifest.migration_head_sha256 or 'unresolved'}`",
        f"- Collector: `{manifest.collector_tool}/{manifest.collector_version}`",
        f"- Schemas: `{counts['schemas']}`",
        f"- Tables: `{counts['tables']}`",
        f"- Views: `{counts['views']}`",
        f"- Columns: `{counts['columns']}`",
        "",
        "Security note: this derivative contains schema metadata only. It does not contain rows, sample values, SQL/DDL bodies, connection strings, hostnames, credentials, or executable queries.",
        "",
        "## Schemas",
        "",
    ]
    for schema in metadata.schemas:
        owner = _hash_short(schema["owner_principal_sha256"])
        lines.append(f"- `{schema['name']}` (owner proof `{owner}`)")
    lines.extend(["", "## Tables", ""])
    for table in metadata.tables:
        lines.extend(
            [
                f"### `{table['schema']}.{table['name']}`",
                "",
                f"- Kind: `{table['kind']}`",
                f"- Owner proof: `{_hash_short(table['owner_principal_sha256'])}`",
                f"- RLS enabled: `{str(table['rls_enabled']).lower()}`",
                f"- RLS forced: `{str(table['rls_forced']).lower()}`",
                "",
                "#### Columns",
                "",
                "| # | Name | Type | Nullable | Generated | Identity | Default proof |",
                "|---:|---|---|---|---|---|---|",
            ]
        )
        for column in table["columns"]:
            lines.append(
                f"| {column['ordinal']} | `{column['name']}` | `{column['data_type']}` | "
                f"`{str(column['nullable']).lower()}` | `{str(column['generated']).lower()}` | "
                f"`{str(column['identity']).lower()}` | `{_hash_short(column['default_expression_sha256'])}` |"
            )
        if table["constraints"]:
            lines.extend(["", "#### Constraints", ""])
            for constraint in table["constraints"]:
                target = ""
                if constraint["type"] == "foreign_key":
                    target = (
                        f" -> `{constraint['referenced_schema']}.{constraint['referenced_table']}"
                        f"({', '.join(constraint['referenced_columns'])})`"
                    )
                lines.append(
                    f"- `{constraint['name']}` `{constraint['type']}` "
                    f"on `{', '.join(constraint['columns'])}`{target}"
                )
        if table["indexes"]:
            lines.extend(["", "#### Indexes", ""])
            for index in table["indexes"]:
                lines.append(
                    f"- `{index['name']}` method `{index['method']}`, columns "
                    f"`{', '.join(index['columns']) or 'expression-only'}`, "
                    f"unique `{str(index['unique']).lower()}`, primary `{str(index['primary']).lower()}`"
                )
        if table["grants"]:
            lines.extend(["", "#### Grants", ""])
            for grant in table["grants"]:
                lines.append(
                    f"- principal proof `{grant['principal_sha256'][:12]}`: "
                    f"`{', '.join(grant['privileges'])}`, grantable `{str(grant['grantable']).lower()}`"
                )
        if table["rls_policies"]:
            lines.extend(["", "#### RLS Policies", ""])
            for policy in table["rls_policies"]:
                lines.append(
                    f"- `{policy['name']}` command `{policy['command']}`, "
                    f"permissive `{str(policy['permissive']).lower()}`, "
                    f"roles `{len(policy['role_principal_hashes'])}`, "
                    f"using proof `{_hash_short(policy['using_expression_sha256'])}`, "
                    f"check proof `{_hash_short(policy['check_expression_sha256'])}`"
                )
        lines.append("")
    lines.extend(["## Views", ""])
    if not metadata.views:
        lines.append("No views declared.")
    for view in metadata.views:
        kind = "materialized view" if view["materialized"] else "view"
        lines.extend(
            [
                f"### `{view['schema']}.{view['name']}`",
                "",
                f"- Kind: `{kind}`",
                f"- Definition proof: `{view['definition_sha256'][:12]}`",
                f"- Columns: `{', '.join(column['name'] for column in view['columns'])}`",
                "- Dependencies:",
            ]
        )
        if view["dependencies"]:
            for dependency in view["dependencies"]:
                lines.append(
                    f"  - `{dependency['kind']}` `{dependency['schema']}.{dependency['name']}`"
                )
        else:
            lines.append("  - none declared")
        lines.append("")
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")
