from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import ConfigurationError, IntegrityError
from .m23_cloudflare_qdrant import CloudflareConfig
from .m25_blog_candidate_release import build_pack_artifacts
from .m25_blog_pilot import (
    ARTICLE_PATH_RE,
    SERIES_META_PATH,
    GitHubClient,
    TreeBlob,
    build_article_record,
    build_nodes_and_edges,
    git_blob_sha,
    parse_series_catalog,
)
from .m26_active_release_dense import ActiveReleaseDenseConfig, ActiveReleaseQdrantDenseChannel
from .m26_admin_contract import CapabilityGate, canonical_json_bytes, utc_now
from .m26_admin_ingestion import CAP_INGESTION_JOB_CONFIRM
from .m26_ingestion_candidate_qdrant import CloudflareQdrantCandidateMaterializer
from .m26_ingestion_finalization import ProductionIngestionFinalizer
from .m26_ingestion_qdrant_qualification import (
    QdrantQualificationConfig,
    QdrantReadOnlyQualificationObserver,
)
from .m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    SQLiteIngestionLedger,
    SQLiteIngestionReadAuthority,
    active_manifest_observer_from_store,
    build_sqlite_ingestion_adapter,
    candidate_executor_from_primitives,
    candidate_manifest_observer_from_store,
)
from .storage import ObjectStore, create_object_store, sha256_bytes

SOURCE_REPOSITORY_ENV = "M26_SOURCE_REPOSITORY"
SOURCE_REF_ENV = "M26_SOURCE_REF"
SOURCE_ROOT_ENV = "M26_SOURCE_ROOT"
SOURCE_TOKEN_ENV = "KNOWLEDGE_SOURCE_READ_TOKEN"
ENGINE_SHA_ENV = "M26_QUERY_BUILD_SHA"
ACTIVATION_ENABLED_ENV = "M26_INGESTION_PRODUCTION_ACTIVATION_ENABLED"
OWNER_AUTHORIZATION_ENV = "M26_INGESTION_OWNER_AUTHORIZATION"
ASK_PROBE_ENV = "M26_INGESTION_ASK_PROBE_QUESTION"
SOURCE_REPOSITORY = "danielcanfly/daniel-blog"
SOURCE_REF = "main"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_PRODUCTION_INGESTION_CAPABILITY_DIGEST = hashlib.sha256(
    canonical_json_bytes(
        [CAP_INGESTION_JOB_CONFIRM, "production_activation", "F8_PRODUCTION_FINALIZATION_QUALIFIED"]
    )
).hexdigest()


@dataclass(frozen=True)
class BlogSnapshot:
    repository: str
    commit_sha: str
    committed_at: str
    documents: tuple[Mapping[str, Any], ...]
    source_identity_digest: str
    article_by_id: Mapping[str, Mapping[str, Any]]
    source_bytes: Mapping[str, bytes]
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]


class BlogSource(Protocol):
    def observe(self) -> Mapping[str, Any]: ...

    def artifact_builder(self, engine_commit_sha: str) -> Any: ...


def _source_identity(documents: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json_bytes({"documents": list(documents)})).hexdigest()


def _snapshot_from_blobs(
    *,
    repository: str,
    commit_sha: str,
    committed_at: str,
    blobs: Sequence[TreeBlob],
    read_blob: Any,
) -> BlogSnapshot:
    if repository != SOURCE_REPOSITORY or not _SHA40.fullmatch(commit_sha):
        raise IntegrityError("BP5-R8 source authority identity is invalid")
    articles = sorted(
        (blob for blob in blobs if ARTICLE_PATH_RE.fullmatch(blob.path)),
        key=lambda item: item.path,
    )
    catalog = [blob for blob in blobs if blob.path == SERIES_META_PATH]
    if not articles or len(catalog) != 1:
        raise IntegrityError("BP5-R8 authoritative blog source is incomplete")
    series_catalog = parse_series_catalog(read_blob(catalog[0]))
    records: list[dict[str, Any]] = []
    raw_by_slug: dict[str, bytes] = {}
    source_bytes: dict[str, bytes] = {}
    documents: list[dict[str, Any]] = []
    for blob in articles:
        raw = read_blob(blob)
        if git_blob_sha(raw) != blob.sha:
            raise IntegrityError("BP5-R8 authoritative blog blob identity mismatch")
        record = build_article_record(
            repository=repository,
            commit=commit_sha,
            tree_blob=blob,
            raw=raw,
            series_catalog=series_catalog,
        )
        article_id = str(record["article_id"])
        slug = str(record["slug"])
        if article_id in source_bytes or slug in raw_by_slug:
            raise IntegrityError("BP5-R8 authoritative blog identity is duplicated")
        records.append(record)
        source_bytes[article_id] = raw
        raw_by_slug[slug] = raw
        documents.append(
            {
                "document_id": article_id,
                "digest": sha256_bytes(raw),
                "origin_path": blob.path,
                "origin_blob_sha": blob.sha,
                "bytes": len(raw),
            }
        )
    documents.sort(key=lambda item: item["document_id"])
    nodes, edges = build_nodes_and_edges(records, raw_by_slug)
    return BlogSnapshot(
        repository=repository,
        commit_sha=commit_sha,
        committed_at=committed_at,
        documents=tuple(documents),
        source_identity_digest=_source_identity(documents),
        article_by_id={str(record["article_id"]): record for record in records},
        source_bytes=source_bytes,
        nodes=tuple(nodes),
        edges=tuple(edges),
    )


class GitHubBlogSource:
    def __init__(
        self,
        *,
        repository: str,
        ref: str,
        client: GitHubClient,
    ) -> None:
        if repository != SOURCE_REPOSITORY or not ref.strip():
            raise ConfigurationError("BP5-R8 source repository/ref is not qualified")
        self.repository = repository
        self.ref = ref
        self.client = client

    def _snapshot(self, ref: str | None = None) -> BlogSnapshot:
        commit, committed_at = self.client.resolve_commit(self.repository, ref or self.ref)
        blobs = self.client.tree(self.repository, commit)
        selected = [
            blob
            for blob in blobs
            if ARTICLE_PATH_RE.fullmatch(blob.path) or blob.path == SERIES_META_PATH
        ]
        source_bytes = self.client.archive_files(
            self.repository,
            commit,
            (blob.path for blob in selected),
        )
        return _snapshot_from_blobs(
            repository=self.repository,
            commit_sha=commit,
            committed_at=committed_at,
            blobs=selected,
            read_blob=lambda blob: source_bytes[blob.path],
        )

    def observe(self) -> Mapping[str, Any]:
        snapshot = self._snapshot()
        return _observation(snapshot)

    def artifact_builder(self, engine_commit_sha: str) -> Any:
        return _artifact_builder(self, engine_commit_sha)


class LocalBlogSource:
    def __init__(self, root: str | Path, *, repository: str = SOURCE_REPOSITORY) -> None:
        self.root = Path(root).expanduser().resolve()
        self.repository = repository

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise IntegrityError("BP5-R8 local source Git identity is unavailable")
        return completed.stdout.strip()

    def _snapshot(self, ref: str | None = None) -> BlogSnapshot:
        commit = self._git("rev-parse", ref or "HEAD").lower()
        if self._git("status", "--porcelain", "--untracked-files=all"):
            raise IntegrityError("BP5-R8 local source checkout is dirty")
        committed_at = self._git("show", "-s", "--format=%cI", commit)
        paths = [
            item
            for item in self._git("ls-tree", "-r", "--name-only", commit).splitlines()
            if ARTICLE_PATH_RE.fullmatch(item) or item == SERIES_META_PATH
        ]
        blobs = [
            TreeBlob(
                path=path,
                sha=self._git("rev-parse", f"{commit}:{path}"),
                size=len((self.root / path).read_bytes()),
            )
            for path in paths
        ]
        return _snapshot_from_blobs(
            repository=self.repository,
            commit_sha=commit,
            committed_at=committed_at,
            blobs=blobs,
            read_blob=lambda blob: (self.root / blob.path).read_bytes(),
        )

    def observe(self) -> Mapping[str, Any]:
        return _observation(self._snapshot())

    def artifact_builder(self, engine_commit_sha: str) -> Any:
        return _artifact_builder(self, engine_commit_sha)


def _observation(snapshot: BlogSnapshot) -> dict[str, Any]:
    return {
        "source_revision": f"git:{snapshot.commit_sha}",
        "source_identity_digest": snapshot.source_identity_digest,
        "documents": [dict(item) for item in snapshot.documents],
    }


def _artifact_builder(source: Any, engine_commit_sha: str) -> Any:
    if not _SHA40.fullmatch(engine_commit_sha):
        raise ConfigurationError("M26_QUERY_BUILD_SHA must be an exact lowercase Git SHA")

    def build(context: Mapping[str, Any]) -> Mapping[str, Any]:
        observed = context.get("source")
        if not isinstance(observed, Mapping):
            raise IntegrityError("BP5-R8 source observation is missing")
        revision = str(observed.get("source_revision") or "")
        if not revision.startswith("git:") or not _SHA40.fullmatch(revision[4:]):
            raise IntegrityError("BP5-R8 source revision is not immutable")
        snapshot = source._snapshot(revision[4:])
        if _observation(snapshot) != dict(observed):
            raise IntegrityError("BP5-R8 source changed after plan revalidation")
        release_id = (
            f"m26blog-{snapshot.commit_sha[:12]}-"
            f"{snapshot.source_identity_digest[:12]}-{engine_commit_sha[:12]}"
        )
        built = build_pack_artifacts(
            {
                "article_by_id": snapshot.article_by_id,
                "source_bytes": snapshot.source_bytes,
                "nodes": snapshot.nodes,
                "edges": snapshot.edges,
            },
            release_id,
            document_namespace="daniel-blog-en",
            expected_semantic_count=None,
        )
        lexical = [
            {
                **dict(row),
                "release_id": release_id,
                "source_commit_sha": snapshot.commit_sha,
                "source_repository_head_sha": snapshot.commit_sha,
                "admission_sha256": snapshot.source_identity_digest,
            }
            for row in built["lexical_documents"]
        ]
        semantic = []
        for row in built["semantic_inputs"]:
            text = str(row["text"])
            payload = dict(row["payload"])
            payload.update(
                {
                    "release_id": release_id,
                    "source_commit_sha": snapshot.commit_sha,
                    "source_repository_head_sha": snapshot.commit_sha,
                    "admission_sha256": snapshot.source_identity_digest,
                    "text_sha256": sha256_bytes(text.encode("utf-8")),
                    "candidate_release_eligible": True,
                    "production_authority": False,
                }
            )
            semantic.append({**dict(row), "payload": payload})
        source_rows = [dict(row) for row in built["source_index"]]
        artifacts = {
            "document_pack_admission": {
                "schema_version": "knowledge-engine-document-pack-admission/v1",
                "release_id": release_id,
                "source_repository": snapshot.repository,
                "source_commit_sha": snapshot.commit_sha,
                "source_repository_head_sha": snapshot.commit_sha,
                "source_admission_sha256": snapshot.source_identity_digest,
                "source_count": len(snapshot.documents),
                "candidate_only_source_release": True,
                "production_pointer_authorized_by_source": False,
            },
            "document_source_index": {
                "schema_version": "knowledge-engine-document-source-index/v1",
                "release_id": release_id,
                "source_count": len(snapshot.documents),
                "entries": source_rows,
            },
            "graph": {
                "schema_version": "knowledge-engine-document-graph/v1",
                "release_id": release_id,
                "nodes": built["graph_nodes"],
                "edges": built["graph_edges"],
            },
            "graph_v2": {
                "schema_version": "knowledge-engine-graph-v2/v1",
                "release": {
                    "release_id": release_id,
                    "engine_commit_sha": engine_commit_sha,
                    "source_commit_sha": snapshot.commit_sha,
                },
                "nodes": built["graph_v2_nodes"],
                "edges": built["graph_v2_edges"],
            },
            "lexical_index": {
                "schema_version": "knowledge-engine-lexical-index/v2",
                "release_id": release_id,
                "documents": lexical,
            },
            "provenance": {
                "schema_version": "knowledge-engine-document-provenance/v1",
                "release_id": release_id,
                "records": built["provenance"],
            },
            "semantic_inputs": {
                "schema_version": "knowledge-engine-semantic-inputs/v1",
                "release_id": release_id,
                "documents": semantic,
            },
            "source_documents": {
                "schema_version": "knowledge-engine-source-documents/v1",
                "release_id": release_id,
                "source_count": len(snapshot.documents),
                "documents": [
                    {
                        "document_id": row["document_id"],
                        "source_id": row["document_id"],
                        "origin_path": row["origin_path"],
                        "content_sha256": row["digest"],
                        "text": snapshot.source_bytes[str(row["document_id"])].decode("utf-8"),
                    }
                    for row in snapshot.documents
                ],
            },
        }
        return {
            "release_id": release_id,
            "engine_commit_sha": engine_commit_sha,
            "source_commit_sha": snapshot.commit_sha,
            "source_repository_head_sha": snapshot.commit_sha,
            "admission_sha256": snapshot.source_identity_digest,
            "source_count": len(snapshot.documents),
            "artifact_bytes": {
                kind: canonical_json_bytes(payload) for kind, payload in artifacts.items()
            },
            "created_at": snapshot.committed_at,
        }

    return build


@dataclass(frozen=True)
class _IngestionCapabilityGate(CapabilityGate):
    qualification_status: str = "qualified"
    effective_state: str = "enabled"
    mutation_authorized: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload = super().to_payload()
        payload.update(
            {
                "qualification_status": self.qualification_status,
                "effective_state": self.effective_state,
                "mutation_authorized": self.mutation_authorized,
            }
        )
        return payload


class CombinedCapabilityProvider:
    def __init__(self, primary: Any, adapter: Any) -> None:
        self.primary = primary
        finalizer = getattr(adapter, "finalization_executor", None)
        authority = getattr(adapter, "finalization_authority_evidence", None)
        qualified = (
            isinstance(adapter, SQLiteIngestionAdapter)
            and isinstance(finalizer, ProductionIngestionFinalizer)
            and getattr(adapter, "finalization_mode", None) == "production_activation"
            and isinstance(authority, Mapping)
            and authority.get("production_activation_authorized") is True
        )
        self._ingestion = (
            {
                CAP_INGESTION_JOB_CONFIRM: _IngestionCapabilityGate(
                    capability_id=CAP_INGESTION_JOB_CONFIRM,
                    state="enabled",
                    reason_code="F8_PRODUCTION_FINALIZATION_QUALIFIED",
                    source="f8_production_runtime_composition",
                    resource_identity={
                        "mode": "production_activation",
                        "production_activation_authorized": True,
                        "public_production_traffic_authorized": False,
                        "deployment_authorized": False,
                    },
                    evidence_digest=_PRODUCTION_INGESTION_CAPABILITY_DIGEST,
                )
            }
            if qualified
            else {}
        )

    def list_capabilities(self) -> list[CapabilityGate]:
        values = {gate.capability_id: gate for gate in self.primary.list_capabilities()}
        values.update(self._ingestion)
        return [values[key] for key in sorted(values)]

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return self._ingestion.get(capability_id) or self.primary.get_capability(capability_id)


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().casefold() in {"1", "true", "yes", "on"}


def _durable_path() -> str:
    return (
        os.getenv("M26_INGESTION_STATE_DB", "").strip()
        or os.getenv("M26_ADMIN_CONTROL_DB_PATH", "").strip()
    )


def _read_only_runtime(
    missing: Sequence[str],
    *,
    source_observer: Any | None = None,
    active_manifest_observer: Any | None = None,
    candidate_manifest_observer: Any | None = None,
) -> SQLiteIngestionReadAuthority:
    path = _durable_path()
    observed_missing = set(missing)
    if not path:
        observed_missing.add("M26_INGESTION_STATE_DB")
        path = str(Path(tempfile.gettempdir()) / f"m26-ingestion-read-only-{os.getpid()}.sqlite3")
    try:
        ledger = SQLiteIngestionLedger(path)
    except Exception:
        observed_missing.add("durable_sqlite_initialization")
        fallback = (
            Path(tempfile.gettempdir()) / f"m26-ingestion-read-only-fallback-{os.getpid()}.sqlite3"
        )
        ledger = SQLiteIngestionLedger(fallback)
    return SQLiteIngestionReadAuthority(
        ledger,
        sorted(observed_missing),
        source_observer=source_observer,
        active_manifest_observer=active_manifest_observer,
        candidate_manifest_observer=candidate_manifest_observer,
        finalization_mode="blocked",
    )


def _production_authority_missing() -> list[str]:
    missing: list[str] = []
    if not _enabled("M26_INGESTION_ENABLED"):
        missing.append("M26_INGESTION_ENABLED")
    if not _enabled(ACTIVATION_ENABLED_ENV):
        missing.append(ACTIVATION_ENABLED_ENV)
    if not os.getenv(OWNER_AUTHORIZATION_ENV, "").strip():
        missing.append(OWNER_AUTHORIZATION_ENV)
    if not os.getenv(ASK_PROBE_ENV, "").strip():
        missing.append(ASK_PROBE_ENV)
    if not _durable_path():
        missing.append("M26_INGESTION_STATE_DB")
    engine_sha = os.getenv(ENGINE_SHA_ENV, "").strip()
    if not _SHA40.fullmatch(engine_sha):
        missing.append(ENGINE_SHA_ENV)
    source_root = os.getenv(SOURCE_ROOT_ENV, "").strip()
    source_token = os.getenv(SOURCE_TOKEN_ENV, "").strip()
    if source_root:
        if not Path(source_root).expanduser().is_dir():
            missing.append(SOURCE_ROOT_ENV)
    elif source_token:
        if os.getenv(SOURCE_REPOSITORY_ENV, SOURCE_REPOSITORY).strip() != SOURCE_REPOSITORY:
            missing.append(SOURCE_REPOSITORY_ENV)
        if os.getenv(SOURCE_REF_ENV, SOURCE_REF).strip() != SOURCE_REF:
            missing.append(SOURCE_REF_ENV)
    else:
        missing.append(f"{SOURCE_ROOT_ENV}|{SOURCE_TOKEN_ENV}")
    if os.getenv("OBJECT_STORE_BACKEND", "").strip().casefold() != "r2":
        missing.append("OBJECT_STORE_BACKEND")
    for name in (
        "R2_ENDPOINT_URL",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_AI_TOKEN",
    ):
        if not os.getenv(name, "").strip():
            missing.append(name)
    read_key = (
        os.getenv("QDRANT_API_KEY_READ", "").strip()
        or os.getenv("QDRANT_READ_ONLY_API_KEY", "").strip()
    )
    if not read_key:
        missing.append("QDRANT_API_KEY_READ|QDRANT_READ_ONLY_API_KEY")
    elif read_key == os.getenv("QDRANT_API_KEY", "").strip():
        missing.append("QDRANT_READ_CREDENTIAL_DISTINCT")
    return sorted(set(missing))


def _production_authority_identity(settings: Any) -> dict[str, Any]:
    source_root = os.getenv(SOURCE_ROOT_ENV, "").strip()
    source_identity = (
        {
            "mode": "local_git",
            "root": str(Path(source_root).expanduser().resolve()),
            "repository": SOURCE_REPOSITORY,
        }
        if source_root
        else {
            "mode": "github",
            "repository": os.getenv(SOURCE_REPOSITORY_ENV, SOURCE_REPOSITORY).strip(),
            "ref": os.getenv(SOURCE_REF_ENV, SOURCE_REF).strip(),
        }
    )
    return {
        "schema_version": "knowledge-engine-m26-production-runtime-authority/v1",
        "object_store_backend": settings.object_store_backend,
        "r2_endpoint_url": settings.r2_endpoint_url,
        "r2_bucket": settings.r2_bucket,
        "r2_region": settings.r2_region,
        "source": source_identity,
        "qdrant_url": os.getenv("QDRANT_URL", "").strip().rstrip("/"),
        "cloudflare_account_id": os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        "engine_commit_sha": os.getenv(ENGINE_SHA_ENV, "").strip(),
        "durable_state_path": str(Path(_durable_path()).expanduser().resolve()),
    }


def build_runtime_ingestion_adapter_from_env(
    *,
    source_override: BlogSource | None = None,
    store_override: ObjectStore | None = None,
    qdrant_observer_override: Any | None = None,
    dense_channel_override: Any | None = None,
    settings_factory: Callable[[], Any] | None = None,
    materializer_factory: Callable[..., Any] | None = None,
    finalizer_factory: Callable[..., ProductionIngestionFinalizer] | None = None,
) -> Any:
    enabled = os.getenv("M26_INGESTION_ENABLED", "false").strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        durable_path = _durable_path()
        if not durable_path:
            return None
        try:
            from .config import Settings

            settings = Settings.from_env()
            store = create_object_store(settings)
            if settings.object_store_backend == "filesystem":
                return SQLiteIngestionReadAuthority(
                    SQLiteIngestionLedger(durable_path),
                    ["M26_INGESTION_ENABLED"],
                    active_manifest_observer=active_manifest_observer_from_store(store),
                    candidate_manifest_observer=candidate_manifest_observer_from_store(store),
                    finalization_mode="blocked",
                )
        except Exception:
            return _read_only_runtime(["M26_INGESTION_ENABLED"])
        return _read_only_runtime(["M26_INGESTION_ENABLED"])
    missing = _production_authority_missing()
    if missing:
        return _read_only_runtime(missing)
    required = {
        ENGINE_SHA_ENV: os.environ[ENGINE_SHA_ENV].strip(),
        "QDRANT_URL": os.environ["QDRANT_URL"].strip(),
        "QDRANT_API_KEY": os.environ["QDRANT_API_KEY"].strip(),
        "CLOUDFLARE_ACCOUNT_ID": os.environ["CLOUDFLARE_ACCOUNT_ID"].strip(),
        "CLOUDFLARE_AI_TOKEN": os.environ["CLOUDFLARE_AI_TOKEN"].strip(),
    }
    source_root = os.getenv(SOURCE_ROOT_ENV, "").strip()
    source_token = os.getenv(SOURCE_TOKEN_ENV, "").strip()
    if source_override is not None:
        source = source_override
    elif source_root:
        source: BlogSource = LocalBlogSource(source_root)
    else:
        source = GitHubBlogSource(
            repository=os.getenv(SOURCE_REPOSITORY_ENV, SOURCE_REPOSITORY).strip(),
            ref=os.getenv(SOURCE_REF_ENV, SOURCE_REF).strip(),
            client=GitHubClient(source_token),
        )
    from .config import Settings

    load_settings = settings_factory or Settings.from_env
    try:
        settings = load_settings()
        store = store_override if store_override is not None else create_object_store(settings)
    except Exception:
        return _read_only_runtime(["object_store_configuration"])
    if settings.object_store_backend != "r2":
        return _read_only_runtime(["OBJECT_STORE_BACKEND"])
    authority_identity = _production_authority_identity(settings)
    read_key = (
        os.getenv("QDRANT_API_KEY_READ", "").strip()
        or os.getenv("QDRANT_READ_ONLY_API_KEY", "").strip()
    )
    try:
        qdrant_observer = qdrant_observer_override or QdrantReadOnlyQualificationObserver(
            QdrantQualificationConfig(url=required["QDRANT_URL"], api_key=read_key)
        )
        dense_channel = dense_channel_override or ActiveReleaseQdrantDenseChannel(
            ActiveReleaseDenseConfig(
                cloudflare_account_id=required["CLOUDFLARE_ACCOUNT_ID"],
                cloudflare_api_token=required["CLOUDFLARE_AI_TOKEN"],
                qdrant_url=required["QDRANT_URL"],
                qdrant_api_key=read_key,
            )
        )
    except Exception:
        return _read_only_runtime(["qdrant_configuration"])
    owner_authorization = os.environ[OWNER_AUTHORIZATION_ENV].strip()

    def authority_check() -> Mapping[str, Any]:
        revoked = _production_authority_missing()
        if revoked or os.getenv(OWNER_AUTHORIZATION_ENV, "").strip() != owner_authorization:
            raise ConfigurationError(
                "F8 production activation authority is incomplete or has been revoked"
            )
        current = load_settings()
        if current.object_store_backend != "r2":
            raise ConfigurationError("F8 production activation requires R2 authority")
        current_identity = _production_authority_identity(current)
        if current_identity != authority_identity:
            raise ConfigurationError("F8 production activation runtime identity changed")
        return current_identity

    make_finalizer = finalizer_factory or ProductionIngestionFinalizer
    try:
        finalizer = make_finalizer(
            store=store,
            source_observer=source.observe,
            qdrant_observer=qdrant_observer,
            dense_channel=dense_channel,
            ask_probe_question=os.environ[ASK_PROBE_ENV].strip(),
            owner_authorization=owner_authorization,
            promoted_at_factory=utc_now,
            authority_check=authority_check,
        )
        authority_evidence = finalizer.self_check()
    except Exception:
        return _read_only_runtime(
            ["production_finalizer_self_check"],
            source_observer=source.observe,
            active_manifest_observer=active_manifest_observer_from_store(store),
            candidate_manifest_observer=candidate_manifest_observer_from_store(store),
        )
    try:
        make_materializer = materializer_factory or CloudflareQdrantCandidateMaterializer
        materializer = make_materializer(
            cloudflare=CloudflareConfig(
                account_id=required["CLOUDFLARE_ACCOUNT_ID"],
                api_token=required["CLOUDFLARE_AI_TOKEN"],
            ),
            qdrant_base_url=required["QDRANT_URL"],
            qdrant_api_key=required["QDRANT_API_KEY"],
        )
        executor = candidate_executor_from_primitives(
            store=store,
            vector_materializer=materializer,
            artifact_builder=source.artifact_builder(required[ENGINE_SHA_ENV]),
        )
    except Exception:
        return _read_only_runtime(
            ["candidate_executor_configuration"],
            source_observer=source.observe,
            active_manifest_observer=active_manifest_observer_from_store(store),
            candidate_manifest_observer=candidate_manifest_observer_from_store(store),
        )
    return build_sqlite_ingestion_adapter(
        source_observer=source.observe,
        active_manifest_observer=active_manifest_observer_from_store(store),
        candidate_manifest_observer=candidate_manifest_observer_from_store(store),
        candidate_executor=executor,
        finalization_executor=finalizer,
        finalization_mode="production_activation",
        finalization_authority_evidence=authority_evidence,
    )


__all__ = [
    "CombinedCapabilityProvider",
    "GitHubBlogSource",
    "LocalBlogSource",
    "ProductionIngestionFinalizer",
    "build_runtime_ingestion_adapter_from_env",
]
