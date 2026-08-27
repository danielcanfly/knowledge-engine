from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from knowledge_engine.m26_production_answer_bundle import load_production_answer_bundle
from knowledge_engine.storage import FileObjectStore, R2ObjectStore


def client_error(code: str, status: int | None = None) -> ClientError:
    response: dict[str, object] = {"Error": {"Code": code, "Message": code}}
    if status is not None:
        response["ResponseMetadata"] = {"HTTPStatusCode": status}
    return ClientError(response, "GetObject")


class FakeS3Client:
    def __init__(self, *, get_error: ClientError | None = None, body: bytes = b"ok") -> None:
        self.get_error = get_error
        self.body = body
        self.get_calls: list[tuple[str, str]] = []
        self.put_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.get_calls.append((Bucket, Key))
        if self.get_error is not None:
            raise self.get_error
        return {"Body": BytesIO(self.body)}

    def put_object(self, **kwargs: object) -> None:
        self.put_calls.append(kwargs)

    def delete_object(self, **kwargs: object) -> None:
        self.delete_calls.append(kwargs)


def store_for(client: FakeS3Client) -> R2ObjectStore:
    store = object.__new__(R2ObjectStore)
    store.bucket = "unit-test-bucket"
    store.client = client
    return store


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("NoSuchKey", None),
        ("404", None),
        ("NotFound", None),
        ("AccessDenied", 404),
    ],
)
def test_r2_get_missing_object_codes_become_file_not_found(code: str, status: int | None) -> None:
    client = FakeS3Client(get_error=client_error(code, status))
    with pytest.raises(FileNotFoundError) as raised:
        store_for(client).get("channels/m26-e4-v3-isolated.json")
    assert "channels/m26-e4-v3-isolated.json" in str(raised.value)
    assert client.put_calls == []
    assert client.delete_calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("AccessDenied", 403),
        ("InternalError", 500),
        ("ServiceUnavailable", 503),
        ("Throttling", 429),
        ("SignatureDoesNotMatch", 403),
    ],
)
def test_r2_get_non_missing_client_errors_propagate_fail_closed(code: str, status: int) -> None:
    err = client_error(code, status)
    client = FakeS3Client(get_error=err)
    with pytest.raises(ClientError) as raised:
        store_for(client).get("releases/x/manifest.json")
    assert raised.value is err
    assert client.put_calls == []
    assert client.delete_calls == []


def test_r2_get_success_reads_body_without_writes() -> None:
    client = FakeS3Client(body=b'{"ok":true}')
    assert store_for(client).get("releases/x/manifest.json") == b'{"ok":true}'
    assert client.get_calls == [("unit-test-bucket", "releases/x/manifest.json")]
    assert client.put_calls == []
    assert client.delete_calls == []


def test_file_object_store_missing_behavior_unchanged(tmp_path: Path) -> None:
    store = FileObjectStore(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.get("missing.json")
    assert store.head("missing.json") is None
    stored = store.put("present.json", b"{}", content_type="application/json")
    assert stored.key == "present.json"
    assert store.get("present.json") == b"{}"


class AlwaysMissingStore:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.puts = 0

    def get(self, key: str) -> bytes:
        self.keys.append(key)
        raise FileNotFoundError(key)


def test_required_manifest_missing_still_fails_closed() -> None:
    store = AlwaysMissingStore()
    with pytest.raises(FileNotFoundError):
        load_production_answer_bundle(store=store)
    assert store.keys == ["releases/m25blog-5250f8422f4f-f5f01d82c7a1-fe499db2e043/manifest.json"]
    assert store.puts == 0
