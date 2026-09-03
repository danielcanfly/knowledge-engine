from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine import m26_daily_ip_rate_limit as rate_limit_module
from knowledge_engine import m26_translation_gateway_public_api as public_gateway_module


def _set_public_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("OBJECT_STORE_BACKEND", "filesystem")
    monkeypatch.setenv("STAGING_M26_OWNER_SUBJECT_HASH", "owner-hash")
    monkeypatch.setenv("M26_ASK_RATE_LIMIT_DB_PATH", str(tmp_path / "limits.sqlite3"))
    monkeypatch.setenv("M26_ASK_RATE_LIMIT_IP_HASH_SECRET", uuid.uuid4().hex)
    monkeypatch.setenv("M26_ASK_RATE_LIMIT_DAY_TZ", "UTC")
    monkeypatch.setattr(public_gateway_module, "load_production_answer_bundle", lambda: None)


def _ip(last_octet: int) -> str:
    return ".".join(str(part) for part in (198, 51, 100, last_octet))


def _post_headers(last_octet: int) -> dict[str, str]:
    return {"cf-connecting-ip": _ip(last_octet)}


def _fake_answer_run(calls: list[dict[str, Any]]):
    def run(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "answer_text": "A grounded supported answer.",
            "citation_count": 1,
            "source_count": 1,
            "translation_gateway": {
                "translation_applied": False,
                "invariant_check_result": "pass",
            },
        }

    return run


def _assert_exact_429_contract(response) -> None:
    payload = response.json()
    assert response.status_code == 429
    assert payload["error"] == "daily_rate_limit_exceeded"
    assert payload["message"] == "Daily question limit reached."
    assert payload["quota"]["scope"] == "ip-day"
    assert payload["quota"]["limit"] == 10
    assert payload["quota"]["remaining"] == 0
    assert payload["quota"]["reset_at"].endswith("Z")
    assert isinstance(payload["quota"]["reset_in_seconds"], int)
    assert payload["quota"]["reset_in_seconds"] > 0

    reset_seconds = str(payload["quota"]["reset_in_seconds"])
    assert response.headers["retry-after"] == reset_seconds
    assert response.headers["x-m26-ratelimit-limit"] == "10"
    assert response.headers["x-m26-ratelimit-remaining"] == "0"
    assert response.headers["x-m26-ratelimit-scope"] == "ip-day"
    assert response.headers["x-m26-ratelimit-reset"] == reset_seconds
    assert response.headers["x-m26-ratelimit-reset-at"] == payload["quota"]["reset_at"]
    assert "x-ratelimit-limit" not in response.headers
    assert "x-ratelimit-remaining" not in response.headers
    assert "x-ratelimit-reset" not in response.headers


def _client(monkeypatch, tmp_path: Path, calls: list[dict[str, Any]]) -> TestClient:
    _set_public_env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        _fake_answer_run(calls),
    )
    app = public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    return TestClient(app)


def test_daily_limit_allows_first_ten_and_rejects_eleventh_before_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(monkeypatch, tmp_path, calls)

    for _ in range(10):
        response = client.post(
            "/v1/answers",
            headers=_post_headers(11),
            json={"question": "What is safe?"},
        )
        assert response.status_code == 200
        assert response.headers["x-m26-ratelimit-limit"] == "10"

    response = client.post(
        "/v1/answers",
        headers=_post_headers(11),
        json={"question": "What is safe?"},
    )

    _assert_exact_429_contract(response)
    assert len(calls) == 10


def test_daily_limit_resets_on_next_day(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(monkeypatch, tmp_path, calls)
    clock = {"now": datetime(2026, 9, 3, 12, tzinfo=UTC)}
    monkeypatch.setattr(rate_limit_module, "_now_utc", lambda: clock["now"])

    for _ in range(10):
        assert client.post(
            "/v1/answers",
            headers=_post_headers(12),
            json={"question": "What is safe?"},
        ).status_code == 200
    assert client.post(
        "/v1/answers",
        headers=_post_headers(12),
        json={"question": "What is safe?"},
    ).status_code == 429

    clock["now"] = datetime(2026, 9, 4, 0, 1, tzinfo=UTC)
    reset_response = client.post(
        "/v1/answers",
        headers=_post_headers(12),
        json={"question": "What is safe?"},
    )

    assert reset_response.status_code == 200
    assert len(calls) == 11


def test_different_ips_have_independent_daily_quota(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(monkeypatch, tmp_path, calls)

    for _ in range(10):
        assert client.post(
            "/v1/answers",
            headers=_post_headers(13),
            json={"question": "What is safe?"},
        ).status_code == 200
    assert client.post(
        "/v1/answers",
        headers=_post_headers(13),
        json={"question": "What is safe?"},
    ).status_code == 429

    independent = client.post(
        "/v1/answers",
        headers=_post_headers(14),
        json={"question": "What is safe?"},
    )

    assert independent.status_code == 200
    assert len(calls) == 11


def test_health_route_does_not_count_against_daily_quota(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(monkeypatch, tmp_path, calls)

    for _ in range(12):
        assert client.get("/v1/answers/health").status_code == 200
    for _ in range(10):
        assert client.post(
            "/v1/answers",
            headers=_post_headers(15),
            json={"question": "What is safe?"},
        ).status_code == 200

    assert client.post(
        "/v1/answers",
        headers=_post_headers(15),
        json={"question": "What is safe?"},
    ).status_code == 429
    assert len(calls) == 10


def test_owner_bypass_token_skips_guest_quota_across_source_ips(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_public_env(monkeypatch, tmp_path)
    owner_token = uuid.uuid4().hex
    monkeypatch.setenv(
        "M26_ASK_OWNER_BYPASS_TOKEN_SHA256",
        hashlib.sha256(owner_token.encode("utf-8")).hexdigest(),
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        _fake_answer_run(calls),
    )
    app = public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    client = TestClient(app)

    for index in range(12):
        response = client.post(
            "/v1/answers",
            headers={**_post_headers(16 + (index % 2)), "x-m26-owner-bypass": owner_token},
            json={"question": "What is safe?"},
        )
        assert response.status_code == 200

    assert len(calls) == 12

    for last_octet in (16, 17):
        for _ in range(10):
            guest = client.post(
                "/v1/answers",
                headers=_post_headers(last_octet),
                json={"question": "What is safe?"},
            )
            assert guest.status_code == 200
        blocked = client.post(
            "/v1/answers",
            headers=_post_headers(last_octet),
            json={"question": "What is safe?"},
        )
        _assert_exact_429_contract(blocked)


def test_invalid_owner_bypass_token_counts_as_guest_and_blocks_before_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_public_env(monkeypatch, tmp_path)
    owner_token = uuid.uuid4().hex
    monkeypatch.setenv(
        "M26_ASK_OWNER_BYPASS_TOKEN_SHA256",
        hashlib.sha256(owner_token.encode("utf-8")).hexdigest(),
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        _fake_answer_run(calls),
    )
    app = public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    client = TestClient(app)

    for _ in range(10):
        response = client.post(
            "/v1/answers",
            headers={**_post_headers(20), "x-m26-owner-bypass": uuid.uuid4().hex},
            json={"question": "What is safe?"},
        )
        assert response.status_code == 200
    blocked = client.post(
        "/v1/answers",
        headers={**_post_headers(20), "x-m26-owner-bypass": uuid.uuid4().hex},
        json={"question": "What is safe?"},
    )

    _assert_exact_429_contract(blocked)
    assert len(calls) == 10


def test_rate_limit_store_does_not_persist_raw_ip(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    client = _client(monkeypatch, tmp_path, calls)

    assert client.post(
        "/v1/answers",
        headers=_post_headers(18),
        json={"question": "What is safe?"},
    ).status_code == 200

    db_path = tmp_path / "limits.sqlite3"
    with sqlite3.connect(db_path.as_posix()) as connection:
        rows = connection.execute(
            "SELECT day_key, ip_key, request_count FROM m26_ask_daily_ip_counts"
        ).fetchall()
    assert rows
    for _day_key, ip_key, request_count in rows:
        assert ip_key != _ip(18)
        assert request_count == 1


def test_zero_daily_limit_fails_closed(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    _set_public_env(monkeypatch, tmp_path)
    monkeypatch.setenv("M26_ASK_DAILY_IP_LIMIT", "0")
    monkeypatch.setattr(
        public_gateway_module,
        "run_owner_translation_gateway_for_web",
        _fake_answer_run(calls),
    )
    app = public_gateway_module.create_app(root=Path.cwd(), gate_path=Path("gate.json"))
    client = TestClient(app)

    response = client.post(
        "/v1/answers",
        headers=_post_headers(19),
        json={"question": "What is safe?"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["reason_code"] == "M26_ASK_RATE_LIMIT_CONFIG_INVALID"
    assert calls == []


def test_production_requires_durable_db_path_and_ip_hash_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_public_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("M26_ASK_RATE_LIMIT_DB_PATH", raising=False)
    with pytest.raises(
        rate_limit_module.M26DailyRateLimitConfigError,
        match="M26_ASK_RATE_LIMIT_DB_PATH",
    ):
        rate_limit_module.DailyRateLimitConfig.from_env()

    _set_public_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("M26_ASK_RATE_LIMIT_IP_HASH_SECRET", raising=False)
    with pytest.raises(
        rate_limit_module.M26DailyRateLimitConfigError,
        match="M26_ASK_RATE_LIMIT_IP_HASH_SECRET",
    ):
        rate_limit_module.DailyRateLimitConfig.from_env()


def test_no_ip_allowlist_support_remains() -> None:
    forbidden_env = "_".join(("M26", "ASK", "RATE", "LIMIT", "EXEMPT", "IPS"))
    source = Path(rate_limit_module.__file__).read_text(encoding="utf-8")

    assert forbidden_env not in source
    assert "ip_network" not in source
    assert "exempt" not in source.lower()
