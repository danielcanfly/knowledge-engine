from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from .config import Settings
from .m26_admin_corpus import ObjectStoreCorpusAdapter
from .m26_ingestion_health_read import (
    _active_cache_identity,
    _write_cached_health_audit,
    build_active_health_audit,
)
from .m26_ingestion_read_runtime import _read_source_observer
from .m26_runtime_read_cache import write_materialized_read_cache
from .m26_sqlite_ingestion import active_manifest_observer_from_store
from .storage import create_object_store


def _source_observation() -> dict[str, Any]:
    observer, missing = _read_source_observer()
    if not callable(observer):
        raise RuntimeError("RUNTIME_SOURCE_OBSERVER_UNAVAILABLE:" + ",".join(sorted(missing)))
    value = observer()
    if not isinstance(value, Mapping):
        raise RuntimeError("RUNTIME_SOURCE_OBSERVER_INVALID")
    return dict(value)


def _store():
    return create_object_store(Settings.from_env())


def _active_observation() -> dict[str, Any]:
    value = active_manifest_observer_from_store(_store())()
    if not isinstance(value, Mapping):
        raise RuntimeError("RUNTIME_ACTIVE_OBSERVER_INVALID")
    return dict(value)


def _corpus_observation() -> dict[str, Any]:
    value = ObjectStoreCorpusAdapter(_store()).read()
    if not isinstance(value, Mapping):
        raise RuntimeError("RUNTIME_CORPUS_OBSERVER_INVALID")
    return dict(value)


def _refresh_health() -> dict[str, Any]:
    store = _store()
    active = dict(active_manifest_observer_from_store(store)())
    identity = _active_cache_identity(active)
    if not all(identity.values()):
        raise RuntimeError("RUNTIME_HEALTH_ACTIVE_IDENTITY_UNAVAILABLE")
    audit = build_active_health_audit(store=store)
    _write_cached_health_audit(identity, audit)
    if str(audit.get("release_id") or "") != identity["release_id"]:
        raise RuntimeError("RUNTIME_HEALTH_AUDIT_RELEASE_MISMATCH")
    return {
        "release_id": identity["release_id"],
        "status": str(audit.get("status") or "unknown"),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in {"source", "active", "corpus", "health"}:
        raise SystemExit(
            "usage: python -m knowledge_engine.m26_runtime_read_worker "
            "source|active|corpus|health"
        )
    role = args[0]
    if role == "source":
        payload = _source_observation()
        write_materialized_read_cache(role, payload)
        result = {"role": role, "status": "succeeded"}
    elif role == "active":
        payload = _active_observation()
        write_materialized_read_cache(role, payload)
        result = {"role": role, "status": "succeeded"}
    elif role == "corpus":
        payload = _corpus_observation()
        write_materialized_read_cache(role, payload)
        result = {
            "role": role,
            "status": "succeeded",
            "source_count": len(payload.get("sources", [])),
        }
    else:
        result = {"role": role, **_refresh_health()}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
