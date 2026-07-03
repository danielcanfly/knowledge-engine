from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from knowledge_engine.config import Settings
from knowledge_engine.intake import IntakeRequest, IntakeResult, intake_markdown
from knowledge_engine.storage import create_object_store
from knowledge_engine.synthesis import (
    PreparedSynthesis,
    SynthesisRequest,
    ValidatedSynthesis,
    prepare_synthesis,
    validate_synthesis,
)

INTAKE_PACKET_FILES = (
    "draft/concept.md",
    "draft/provenance.json",
    "draft/source-record.json",
    "review-checklist.json",
    "review-packet.json",
)
SYNTHESIS_FILES = (
    "model-output.json",
    "draft/concept.md",
    "draft/claim-provenance.json",
    "unsupported-claims.json",
    "synthesis-record.json",
)
SOURCE_TEXT = (
    "# M5 synthesis integration\n\n"
    "Immutable evidence must remain separate from canonical knowledge.\n"
)


def _intake_keys(result: IntakeResult) -> set[str]:
    return {
        result.raw_blob_key,
        result.capture_metadata_key,
        result.normalized_key,
        *(f"{result.review_packet_prefix}/{path}" for path in INTAKE_PACKET_FILES),
    }


def _request_keys(result: PreparedSynthesis) -> set[str]:
    return {result.request_record_key, result.prompt_envelope_key}


def _synthesis_keys(result: ValidatedSynthesis) -> set[str]:
    return {f"{result.synthesis_prefix}/{path}" for path in SYNTHESIS_FILES}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    suffix = hashlib.sha256(args.run_id.encode()).hexdigest()[:16]
    store = create_object_store(Settings.from_env())
    created_keys: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="knowledge-synthesis-r2-") as temporary:
        root = Path(temporary)
        source = root / "source.md"
        source.write_text(SOURCE_TEXT, encoding="utf-8")
        try:
            intake = intake_markdown(
                store=store,
                request=IntakeRequest(
                    source_id=f"source_m5_syn_{suffix}",
                    source_uri=f"urn:m5-synthesis:{args.run_id}",
                    title="M5 synthesis integration",
                    kind="markdown",
                    audience="internal",
                    retrieved_at="2026-07-03T00:00:00Z",
                    owner="knowledge-engine integration",
                    license="test-only",
                ),
                input_path=source,
                output_dir=root / "intake",
            )
            created_keys.update(_intake_keys(intake))

            request = SynthesisRequest(
                capture_id=intake.capture_id,
                provider="fixture-provider",
                model="fixture-model",
                model_version="fixture-v1",
                prompt_version="m5-prompt-v1",
                harness_version="m5-harness-v1",
                seed=19,
                temperature=0.0,
                requested_at="2026-07-03T00:01:00Z",
                actor="r2-integration",
            )
            prepared = prepare_synthesis(
                store=store,
                request=request,
                output_dir=root / "prepared",
            )
            created_keys.update(_request_keys(prepared))
            prepared_replay = prepare_synthesis(
                store=store,
                request=request,
                output_dir=root / "prepared-replay",
            )
            created_keys.update(_request_keys(prepared_replay))

            quote = "Immutable evidence must remain separate from canonical knowledge."
            start = SOURCE_TEXT.index(quote)
            model_output = root / "model-output.json"
            model_output.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "title": "Evidence separation",
                        "summary": (
                            "The source requires immutable evidence to remain separate "
                            "from canonical knowledge."
                        ),
                        "claims": [
                            {
                                "claim_id": "claim_evidence_separation",
                                "text": quote,
                                "evidence": [
                                    {
                                        "start_char": start,
                                        "end_char": start + len(quote),
                                        "quote": quote,
                                    }
                                ],
                            }
                        ],
                        "unsupported_claims": [],
                    }
                ),
                encoding="utf-8",
            )
            validated = validate_synthesis(
                store=store,
                request_id=prepared.request_id,
                model_output_path=model_output,
                output_dir=root / "validated",
            )
            created_keys.update(_synthesis_keys(validated))
            validated_replay = validate_synthesis(
                store=store,
                request_id=prepared.request_id,
                model_output_path=model_output,
                output_dir=root / "validated-replay",
            )
            created_keys.update(_synthesis_keys(validated_replay))

            if not prepared_replay.idempotent:
                raise RuntimeError("R2 synthesis request replay was not idempotent")
            if not validated_replay.idempotent:
                raise RuntimeError("R2 synthesis validation replay was not idempotent")
            if validated.status != "pending_human_review":
                raise RuntimeError("R2 synthesis entered the wrong review state")
            if validated.canonical_write_permitted:
                raise RuntimeError("R2 synthesis unexpectedly permits canonical writes")
            record = json.loads(
                store.get(f"{validated.synthesis_prefix}/synthesis-record.json")
            )
            if record.get("supported_claim_count") != 1:
                raise RuntimeError("R2 synthesis did not preserve the supported claim")
            if record.get("github_write_permitted") is not False:
                raise RuntimeError("R2 synthesis unexpectedly permits GitHub writes")
            provenance = json.loads(
                store.get(
                    f"{validated.synthesis_prefix}/draft/claim-provenance.json"
                )
            )
            span = provenance["claims"][0]["evidence"][0]
            if SOURCE_TEXT[span["start_char"] : span["end_char"]] != span["quote"]:
                raise RuntimeError("R2 synthesis evidence span failed read-back validation")

            print(
                json.dumps(
                    {
                        "status": "passed",
                        "run_id": args.run_id,
                        "capture_id": intake.capture_id,
                        "request_id": prepared.request_id,
                        "synthesis_id": validated.synthesis_id,
                        "prepare_replay_idempotent": prepared_replay.idempotent,
                        "validate_replay_idempotent": validated_replay.idempotent,
                        "supported_claim_count": validated.supported_claim_count,
                        "canonical_write_permitted": False,
                        "github_write_permitted": False,
                        "production_write_permitted": False,
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
