from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from knowledge_engine.config import Settings
from knowledge_engine.intake import IntakeRequest, IntakeResult, intake_markdown
from knowledge_engine.storage import create_object_store

PACKET_FILES = (
    "draft/concept.md",
    "draft/provenance.json",
    "draft/source-record.json",
    "review-checklist.json",
    "review-packet.json",
)


def _keys(result: IntakeResult) -> set[str]:
    return {
        result.raw_blob_key,
        result.capture_metadata_key,
        result.normalized_key,
        *(f"{result.review_packet_prefix}/{path}" for path in PACKET_FILES),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    suffix = hashlib.sha256(args.run_id.encode()).hexdigest()[:16]
    settings = Settings.from_env()
    store = create_object_store(settings)
    created_keys: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="knowledge-intake-r2-") as temporary:
        root = Path(temporary)
        source = root / "source.md"
        source.write_text(
            "# M5 R2 intake\n\nImmutable evidence capture integration.\n",
            encoding="utf-8",
        )
        request = IntakeRequest(
            source_id=f"source_m5_r2_{suffix}",
            source_uri=f"urn:m5-r2:{args.run_id}",
            title="M5 R2 intake integration",
            kind="markdown",
            audience="internal",
            retrieved_at="2026-07-03T00:00:00Z",
            owner="knowledge-engine integration",
            license="test-only",
        )
        mirror_request = IntakeRequest(
            source_id=f"source_m5_mirror_{suffix}",
            source_uri=f"urn:m5-r2-mirror:{args.run_id}",
            title="M5 R2 intake integration mirror",
            kind="markdown",
            audience="internal",
            retrieved_at="2026-07-03T00:00:00Z",
            owner="knowledge-engine integration",
            license="test-only",
        )

        try:
            first = intake_markdown(
                store=store,
                request=request,
                input_path=source,
                output_dir=root / "first",
            )
            created_keys.update(_keys(first))
            replay = intake_markdown(
                store=store,
                request=request,
                input_path=source,
                output_dir=root / "replay",
            )
            created_keys.update(_keys(replay))
            mirror = intake_markdown(
                store=store,
                request=mirror_request,
                input_path=source,
                output_dir=root / "mirror",
            )
            created_keys.update(_keys(mirror))

            if first.idempotent:
                raise RuntimeError("first R2 intake unexpectedly reported idempotent")
            if not replay.idempotent:
                raise RuntimeError("exact R2 intake replay was not idempotent")
            if replay.capture_id != first.capture_id:
                raise RuntimeError("exact R2 replay changed capture identity")
            if mirror.capture_id == first.capture_id:
                raise RuntimeError("distinct source capture reused capture identity")
            if mirror.raw_blob_key != first.raw_blob_key or not mirror.raw_blob_reused:
                raise RuntimeError("cross-source R2 intake did not reuse raw blob")
            if store.get(first.raw_blob_key) != source.read_bytes():
                raise RuntimeError("R2 raw blob bytes differ from intake source")
            capture = json.loads(store.get(first.capture_metadata_key))
            if capture.get("canonical_write_permitted") is not False:
                raise RuntimeError("R2 capture unexpectedly permits canonical write")
            packet = json.loads(
                store.get(f"{first.review_packet_prefix}/review-packet.json")
            )
            if packet.get("status") != "pending_human_review":
                raise RuntimeError("R2 review packet has the wrong status")

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "run_id": args.run_id,
                        "capture_id": first.capture_id,
                        "raw_blob_key": first.raw_blob_key,
                        "raw_sha256": first.raw_sha256,
                        "replay_idempotent": replay.idempotent,
                        "mirror_capture_id": mirror.capture_id,
                        "mirror_reused_raw_blob": mirror.raw_blob_reused,
                        "canonical_write_permitted": False,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        finally:
            for key in sorted(created_keys, reverse=True):
                store.delete(key)


if __name__ == "__main__":
    raise SystemExit(main())
