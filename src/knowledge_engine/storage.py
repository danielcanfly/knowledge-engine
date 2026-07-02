from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings
from .errors import IntegrityError, ReleaseConflictError


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _etag_for_if_match(etag: str) -> str:
    value = etag.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    if not (value.startswith('"') and value.endswith('"')):
        value = f'"{value.strip(chr(34))}"'
    return value


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    bytes: int
    etag: str
    sha256: str | None
    content_type: str | None


class ObjectStore(Protocol):
    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str | None = None,
        expected_etag: str | None = None,
        only_if_absent: bool = False,
    ) -> ObjectMetadata: ...

    def get(self, key: str) -> bytes: ...

    def head(self, key: str) -> ObjectMetadata | None: ...

    def delete(self, key: str) -> None: ...


class FileObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"object key escapes store root: {key}") from exc
        return path

    def _metadata_path(self, key: str) -> Path:
        return self._path(f".metadata/{key}.json")

    def head(self, key: str) -> ObjectMetadata | None:
        path = self._path(key)
        if not path.is_file():
            return None
        data = path.read_bytes()
        metadata_path = self._metadata_path(key)
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        digest = sha256_bytes(data)
        return ObjectMetadata(
            key=key,
            bytes=len(data),
            etag=digest,
            sha256=metadata.get("sha256", digest),
            content_type=metadata.get("content_type"),
        )

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str | None = None,
        expected_etag: str | None = None,
        only_if_absent: bool = False,
    ) -> ObjectMetadata:
        current = self.head(key)
        if only_if_absent and current is not None:
            raise ReleaseConflictError(f"object already exists: {key}")
        if expected_etag is not None and (
            current is None or current.etag != expected_etag
        ):
            raise ReleaseConflictError(f"compare-and-swap failed for {key}")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        digest = sha256 or sha256_bytes(data)
        metadata_path = self._metadata_path(key)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(
                {"sha256": digest, "content_type": content_type},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return ObjectMetadata(
            key=key,
            bytes=len(data),
            etag=sha256_bytes(data),
            sha256=digest,
            content_type=content_type,
        )

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
        self._metadata_path(key).unlink(missing_ok=True)


class R2ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.r2_bucket or ""
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name=settings.r2_region,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 4, "mode": "adaptive"},
                connect_timeout=10,
                read_timeout=30,
            ),
        )

    def head(self, key: str) -> ObjectMetadata | None:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        metadata = response.get("Metadata", {})
        return ObjectMetadata(
            key=key,
            bytes=int(response.get("ContentLength", 0)),
            etag=str(response.get("ETag", "")).strip(),
            sha256=metadata.get("sha256"),
            content_type=response.get("ContentType"),
        )

    def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        sha256: str | None = None,
        expected_etag: str | None = None,
        only_if_absent: bool = False,
    ) -> ObjectMetadata:
        kwargs: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
            "Metadata": {"sha256": sha256 or sha256_bytes(data)},
        }
        if expected_etag is not None:
            kwargs["IfMatch"] = _etag_for_if_match(expected_etag)
        if only_if_absent:
            kwargs["IfNoneMatch"] = "*"
        try:
            self.client.put_object(**kwargs)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status in {409, 412} or code in {
                "PreconditionFailed",
                "ConditionalRequestConflict",
            }:
                raise ReleaseConflictError(
                    f"conditional write failed for {key}"
                ) from exc
            raise
        metadata = self.head(key)
        if metadata is None:
            raise IntegrityError(f"R2 object missing immediately after upload: {key}")
        return metadata

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "filesystem":
        return FileObjectStore(settings.filesystem_store_root)
    return R2ObjectStore(settings)
