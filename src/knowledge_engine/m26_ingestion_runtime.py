from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
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
from .m26_admin_contract import CapabilityGate, canonical_json_bytes
from .m26_admin_ingestion import CAP_INGESTION_JOB_CONFIRM
from .m26_ingestion_candidate_qdrant import CloudflareQdrantCandidateMaterializer
from .m26_sqlite_ingestion import (
    SQLiteIngestionAdapter,
    build_sqlite_ingestion_adapter,
    candidate_executor_from_primitives,
)
from .storage import create_object_store, sha256_bytes

SOURCE_REPOSITORY_ENV = "M26_SOURCE_REPOSITORY"
SOURCE_REF_ENV = "M26_SOURCE_REF"
SOURCE_ROOT_ENV = "M26_SOURCE_ROOT"
SOURCE_TOKEN_ENV = "KNOWLEDGE_SOURCE_READ_TOKEN"
ENGINE_SHA_ENV = "M26_QUERY_BUILD_SHA"
SOURCE_REPOSITORY = "danielcanfly/daniel-blog"
SOURCE_REF = "main"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_INGESTION_CAPABILITY_DIGEST = hashlib.sha256(
    canonical_json_bytes([CAP_INGESTION_JOB_CONFIRM, "candidate_only"])
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
        self._ingestion = (
            {
                CAP_INGESTION_JOB_CONFIRM: _IngestionCapabilityGate(
                    capability_id=CAP_INGESTION_JOB_CONFIRM,
                    state="enabled",
                    reason_code="BP5_CANDIDATE_ONLY_RUNTIME_QUALIFIED",
                    source="bp5_production_runtime_composition",
                    resource_identity={
                        "mode": "candidate_only",
                        "production_pointer_authorized": False,
                    },
                    evidence_digest=_INGESTION_CAPABILITY_DIGEST,
                )
            }
            if isinstance(adapter, SQLiteIngestionAdapter)
            else {}
        )

    def list_capabilities(self) -> list[CapabilityGate]:
        values = {gate.capability_id: gate for gate in self.primary.list_capabilities()}
        values.update(self._ingestion)
        return [values[key] for key in sorted(values)]

    def get_capability(self, capability_id: str) -> CapabilityGate | None:
        return self._ingestion.get(capability_id) or self.primary.get_capability(capability_id)


def build_runtime_ingestion_adapter_from_env() -> Any:
    enabled = os.getenv("M26_INGESTION_ENABLED", "false").strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        durable_path = (
            os.getenv("M26_INGESTION_STATE_DB", "").strip()
            or os.getenv("M26_ADMIN_CONTROL_DB_PATH", "").strip()
        )
        if not durable_path:
            return None
        return build_sqlite_ingestion_adapter(allow_read_only_when_disabled=True)
    required = {
        ENGINE_SHA_ENV: os.getenv(ENGINE_SHA_ENV, "").strip(),
        "QDRANT_URL": os.getenv("QDRANT_URL", "").strip(),
        "QDRANT_API_KEY": os.getenv("QDRANT_API_KEY", "").strip(),
        "CLOUDFLARE_ACCOUNT_ID": os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip(),
        "CLOUDFLARE_AI_TOKEN": os.getenv("CLOUDFLARE_AI_TOKEN", "").strip(),
    }
    source_root = os.getenv(SOURCE_ROOT_ENV, "").strip()
    source_token = os.getenv(SOURCE_TOKEN_ENV, "").strip()
    if any(not value for value in required.values()) or (not source_root and not source_token):
        return build_sqlite_ingestion_adapter()
    if source_root:
        source: BlogSource = LocalBlogSource(source_root)
    else:
        source = GitHubBlogSource(
            repository=os.getenv(SOURCE_REPOSITORY_ENV, SOURCE_REPOSITORY).strip(),
            ref=os.getenv(SOURCE_REF_ENV, SOURCE_REF).strip(),
            client=GitHubClient(source_token),
        )
    from .config import Settings

    settings = Settings.from_env()
    store = create_object_store(settings)
    materializer = CloudflareQdrantCandidateMaterializer(
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
    return build_sqlite_ingestion_adapter(
        source_observer=source.observe,
        candidate_executor=executor,
    )


__all__ = [
    "CombinedCapabilityProvider",
    "GitHubBlogSource",
    "LocalBlogSource",
    "build_runtime_ingestion_adapter_from_env",
]
