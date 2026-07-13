from __future__ import annotations

import copy

import pytest

from knowledge_engine.errors import IntegrityError
from knowledge_engine.m21_blog_inventory import (
    build_connector_descriptor,
    build_inventory_snapshot,
    canonicalize_url,
)

ALLOWED = {
    "danielcanfly.com",
    "www.danielcanfly.com",
    "raw.githubusercontent.com",
}
IDENTITY = {
    "engine_sha": "e" * 40,
    "source_sha": "s" * 40,
    "foundation_sha": "f" * 40,
    "captured_at": "2026-07-13T16:00:00Z",
}


def _item(slug: str = "rag-part-1") -> dict:
    return {
        "canonical_url": f"https://www.danielcanfly.com/blog/{slug}",
        "language": "en",
        "slug": slug,
        "series": "production-rag",
        "part": 1,
        "published_at": "2026-01-01T08:00:00+08:00",
        "modified_at": "2026-02-01T08:00:00+08:00",
        "content_sha256": "a" * 64,
        "source_kind": "repository_markdown",
        "locator": f"content/en/{slug}.md",
        "redirects": [],
        "translated_counterpart": (
            f"https://www.danielcanfly.com/zh/blog/{slug}"
        ),
        "access_status": "available",
        "intake_status": "captured",
        "ownership_basis": "First-party article owned by Daniel Huang",
        "audience": "public",
    }


def test_url_canonicalization_is_deterministic() -> None:
    assert canonicalize_url(
        "https://WWW.danielcanfly.com/blog/../blog/rag/?page=1",
        allowed_hosts=ALLOWED,
    ) == "https://www.danielcanfly.com/blog/rag/?page=1"


def test_connector_preference_descriptor_is_bounded_and_secret_free() -> None:
    descriptor = build_connector_descriptor(
        {
            "source_kind": "repository_markdown",
            "url": (
                "https://raw.githubusercontent.com/"
                "danielcanfly/site/main/post.md"
            ),
            "media_type": "text/markdown",
            "max_bytes": 200_000,
            "redirect_limit": 0,
        },
        allowed_hosts=ALLOWED,
    )
    assert descriptor.source_kind == "repository_markdown"
    assert descriptor.credentials_required is False
    assert descriptor.max_bytes == 200_000


def test_connector_rejects_non_https_userinfo_private_hosts_and_secrets() -> None:
    base = {
        "source_kind": "https_url",
        "media_type": "text/html",
        "max_bytes": 100,
    }
    for url in (
        "http://www.danielcanfly.com/blog/a",
        "https://user:pass@www.danielcanfly.com/blog/a",
        "https://127.0.0.1/blog/a",
    ):
        with pytest.raises(IntegrityError):
            build_connector_descriptor(
                {**base, "url": url},
                allowed_hosts=ALLOWED | {"127.0.0.1"},
            )
    with pytest.raises(IntegrityError, match="must not require credentials"):
        build_connector_descriptor(
            {
                **base,
                "url": "https://www.danielcanfly.com/blog/a",
                "credentials_required": True,
            },
            allowed_hosts=ALLOWED,
        )


def test_connector_rejects_redirect_payload_and_media_bounds() -> None:
    base = {
        "source_kind": "site_feed",
        "url": "https://www.danielcanfly.com/feed.xml",
        "media_type": "application/rss+xml",
        "max_bytes": 100,
    }
    with pytest.raises(IntegrityError, match="redirect limit"):
        build_connector_descriptor(
            {**base, "redirect_limit": 9},
            allowed_hosts=ALLOWED,
        )
    with pytest.raises(IntegrityError, match="max bytes"):
        build_connector_descriptor(
            {**base, "max_bytes": 8_000_001},
            allowed_hosts=ALLOWED,
        )
    with pytest.raises(IntegrityError, match="media type"):
        build_connector_descriptor(
            {**base, "media_type": "application/octet-stream"},
            allowed_hosts=ALLOWED,
        )


def test_inventory_snapshot_is_stable_sorted_and_evidence_only() -> None:
    second = _item("rag-part-2")
    second["content_sha256"] = "b" * 64
    second["part"] = 2
    snapshot = build_inventory_snapshot(
        IDENTITY,
        [second, _item()],
        allowed_hosts=ALLOWED,
    )
    assert [item["slug"] for item in snapshot["items"]] == [
        "rag-part-1",
        "rag-part-2",
    ]
    assert snapshot["authority"] == "evidence_only"
    assert snapshot["canonical_knowledge"] is False
    assert snapshot["production_authority"] is False
    assert len(snapshot["snapshot_sha256"]) == 64


def test_inventory_timestamps_normalize_to_utc() -> None:
    snapshot = build_inventory_snapshot(
        IDENTITY,
        [_item()],
        allowed_hosts=ALLOWED,
    )
    item = snapshot["items"][0]
    assert item["published_at"] == "2026-01-01T00:00:00Z"
    assert item["modified_at"] == "2026-02-01T00:00:00Z"


def test_duplicate_url_and_content_fail_closed() -> None:
    duplicate_url = _item()
    duplicate_url["content_sha256"] = "b" * 64
    with pytest.raises(IntegrityError, match="duplicate canonical URL"):
        build_inventory_snapshot(
            IDENTITY,
            [_item(), duplicate_url],
            allowed_hosts=ALLOWED,
        )

    duplicate_content = _item("rag-part-2")
    with pytest.raises(IntegrityError, match="duplicate content digest"):
        build_inventory_snapshot(
            IDENTITY,
            [_item(), duplicate_content],
            allowed_hosts=ALLOWED,
        )


def test_redirect_loops_and_host_escape_fail_closed() -> None:
    loop = _item()
    loop["redirects"] = [loop["canonical_url"]]
    with pytest.raises(IntegrityError, match="redirect loop"):
        build_inventory_snapshot(IDENTITY, [loop], allowed_hosts=ALLOWED)

    escape = _item()
    escape["redirects"] = ["https://evil.example/blog/a"]
    with pytest.raises(IntegrityError, match="not allowlisted"):
        build_inventory_snapshot(IDENTITY, [escape], allowed_hosts=ALLOWED)


def test_identity_status_audience_and_item_bounds_fail_closed() -> None:
    bad_identity = copy.deepcopy(IDENTITY)
    bad_identity["source_sha"] = "short"
    with pytest.raises(IntegrityError, match="Source SHA"):
        build_inventory_snapshot(
            bad_identity,
            [_item()],
            allowed_hosts=ALLOWED,
        )

    bad = _item()
    bad["audience"] = "secret"
    with pytest.raises(IntegrityError, match="audience"):
        build_inventory_snapshot(IDENTITY, [bad], allowed_hosts=ALLOWED)

    with pytest.raises(IntegrityError, match="item count"):
        build_inventory_snapshot(IDENTITY, [], allowed_hosts=ALLOWED)


def test_snapshot_is_byte_semantically_reproducible() -> None:
    first = build_inventory_snapshot(
        IDENTITY,
        [_item()],
        allowed_hosts=ALLOWED,
    )
    second = build_inventory_snapshot(
        IDENTITY,
        [_item()],
        allowed_hosts=ALLOWED,
    )
    assert first == second
