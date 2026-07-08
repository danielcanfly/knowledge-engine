from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .intake_v1 import (
    AUDIENCES,
    SNAPSHOT_ID_RE,
    SOURCE_ID_RE,
    AccessPolicy,
    EvidenceValue,
    IntakeFailure,
    IntakeResult,
    _event,
    _event_keys,
    _pretty_json_bytes,
    _prompt_findings,
    _put_immutable,
    _reject,
    _secret_matches,
    _storage_location,
    _validate_utc,
    _write_event,
    _write_output,
    canonical_json_bytes,
    derivative_id_for,
    snapshot_id_for,
    stable_source_id,
)
from .media_bundle import (
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_MAX_MEDIA_BYTES,
    DEFAULT_MAX_SEGMENTS,
    DEFAULT_MAX_TRANSCRIPT_BYTES,
    LocalMediaBundleReader,
    MediaBundle,
    format_timestamp,
    render_derivative,
)
from .storage import ObjectStore, sha256_bytes

CONNECTOR_TYPE = "media_derived_markdown"
CONNECTOR_VERSION = "media-derived-markdown/1.0.0"
NORMALIZER_ID = "media_transcript_markdown"
NORMALIZER_VERSION = "1.0.0"


@dataclass(frozen=True)
class MediaDerivedRequest:
    locator: str
    retrieved_at: str
    owner: EvidenceValue
    license: EvidenceValue
    audience: str
    access_policy: AccessPolicy
    source_id: str | None = None
    parent_snapshot: str | None = None
    max_media_bytes: int = DEFAULT_MAX_MEDIA_BYTES
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES
    max_segments: int = DEFAULT_MAX_SEGMENTS
    max_duration_ms: int = DEFAULT_MAX_DURATION_MS

    def validate(self) -> None:
        if not self.locator or self.locator.strip() != self.locator:
            raise IntakeFailure("INVALID_LOCATOR", "request", "bundle locator is required")
        _validate_utc(self.retrieved_at)
        self.owner.validate("owner")
        self.license.validate("license")
        if self.audience not in AUDIENCES:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid audience")
        self.access_policy.validate(audience=self.audience)
        if self.source_id is not None and SOURCE_ID_RE.fullmatch(self.source_id) is None:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid source_id")
        if self.parent_snapshot is not None and SNAPSHOT_ID_RE.fullmatch(
            self.parent_snapshot
        ) is None:
            raise IntakeFailure("INVALID_METADATA", "request", "invalid parent_snapshot")
        if not 1 <= self.max_media_bytes <= DEFAULT_MAX_MEDIA_BYTES:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_media_bytes is outside connector policy",
            )
        if not 1 <= self.max_transcript_bytes <= DEFAULT_MAX_TRANSCRIPT_BYTES:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_transcript_bytes is outside connector policy",
            )
        if not 1 <= self.max_segments <= 100_000:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_segments is outside connector policy",
            )
        if not 1 <= self.max_duration_ms <= 7 * 24 * 60 * 60 * 1000:
            raise IntakeFailure(
                "INVALID_METADATA",
                "request",
                "max_duration_ms is outside connector policy",
            )

    def attempt_id(self) -> str:
        payload = {
            "schema_version": "intake-attempt/v1",
            "connector_type": CONNECTOR_TYPE,
            "locator": self.locator,
            "retrieved_at": self.retrieved_at,
            "owner": self.owner.to_dict(),
            "license": self.license.to_dict(),
            "audience": self.audience,
            "access_policy": self.access_policy.to_dict(),
            "source_id": self.source_id,
            "parent_snapshot": self.parent_snapshot,
            "max_media_bytes": self.max_media_bytes,
            "max_transcript_bytes": self.max_transcript_bytes,
            "max_segments": self.max_segments,
            "max_duration_ms": self.max_duration_ms,
        }
        return "attempt_" + sha256_bytes(canonical_json_bytes(payload))[:32]


def _raw_keys(bundle: MediaBundle) -> tuple[str, str]:
    media_hash = bundle.manifest.media_sha256
    transcript_hash = bundle.manifest.transcript_sha256
    return (
        f"intake/v1/raw/sha256/{media_hash[:2]}/{media_hash}",
        f"intake/v1/raw/sha256/{transcript_hash[:2]}/{transcript_hash}",
    )


def _evidence(
    *,
    attempt_id: str,
    source_id: str,
    bundle: MediaBundle | None,
    failure: IntakeFailure | None,
) -> dict[str, Any]:
    manifest = bundle.manifest if bundle is not None else None
    media_raw_key = None
    transcript_raw_key = None
    if bundle is not None:
        media_raw_key, transcript_raw_key = _raw_keys(bundle)
    return {
        "schema_version": "media-acquisition-evidence/v1",
        "attempt_id": attempt_id,
        "source_id": source_id,
        "connector_type": CONNECTOR_TYPE,
        "connector_version": CONNECTOR_VERSION,
        "source_uri_sha256": manifest.source_uri_sha256 if manifest else None,
        "manifest_sha256": manifest.manifest_sha256 if manifest else None,
        "media": (
            {
                "sha256": manifest.media_sha256,
                "byte_size": manifest.media_byte_size,
                "media_type": manifest.media_type,
                "duration_ms": manifest.duration_ms,
                "duration_timecode": format_timestamp(manifest.duration_ms),
                "raw_key": media_raw_key,
            }
            if manifest
            else None
        ),
        "transcript": (
            {
                "sha256": manifest.transcript_sha256,
                "byte_size": manifest.transcript_byte_size,
                "language": manifest.language,
                "segment_count": len(manifest.segments),
                "first_start_ms": manifest.segments[0].start_ms,
                "last_end_ms": manifest.segments[-1].end_ms,
                "raw_key": transcript_raw_key,
            }
            if manifest
            else None
        ),
        "acquisition": (
            {
                "tool": manifest.acquisition_tool,
                "version": manifest.acquisition_version,
            }
            if manifest
            else None
        ),
        "transcription": (
            {
                "tool": manifest.transcription_tool,
                "model": manifest.transcription_model,
                "version": manifest.transcription_version,
            }
            if manifest
            else None
        ),
        "bundle_policy": {
            "local_only": True,
            "network_enabled": False,
            "media_download_enabled": False,
            "codec_execution_enabled": False,
            "transcription_enabled": False,
            "diarization_enabled": False,
            "ocr_enabled": False,
            "shell_enabled": False,
            "symlinks_allowed": False,
            "hardlinks_allowed": False,
            "manifest_fields_extensible": False,
        },
        "outcome": "accepted" if failure is None else "rejected",
        "failure_code": failure.code if failure else None,
        "safe_context": failure.safe_context if failure else {},
    }


def intake_media_derived_markdown(
    *,
    store: ObjectStore,
    request: MediaDerivedRequest,
    allowed_root: Path,
    output_dir: Path | None = None,
) -> IntakeResult:
    """Acquire one bounded local media/transcript evidence bundle."""

    attempt_id = request.attempt_id()
    events: list[dict[str, Any]] = []
    object_states: list[bool] = []
    artifacts: dict[str, Any] = {}
    current_state: str | None = None
    bundle: MediaBundle | None = None
    evidence_key: str | None = None
    evidence_written = False

    try:
        request.validate()
        reader = LocalMediaBundleReader(allowed_root)
        bundle = reader.read(
            request.locator,
            max_media_bytes=request.max_media_bytes,
            max_transcript_bytes=request.max_transcript_bytes,
            max_segments=request.max_segments,
            max_duration_ms=request.max_duration_ms,
        )
        manifest = bundle.manifest
        canonical_locator = f"media-derived://source/{manifest.source_uri_sha256}"
        source_id = request.source_id or stable_source_id(CONNECTOR_TYPE, canonical_locator)
        artifacts["source_id"] = source_id
        evidence_key = f"intake/v1/attempts/{attempt_id}/media-acquisition.json"
        artifacts["media_evidence_key"] = evidence_key

        discovered = _event(
            attempt_id=attempt_id,
            sequence=1,
            occurred_at=request.retrieved_at,
            from_state=None,
            to_state="discovered",
            reason_code="SOURCE_DISCOVERED",
            evidence_refs=[
                f"source_uri_sha256:{manifest.source_uri_sha256}",
                f"manifest_sha256:{manifest.manifest_sha256}",
            ],
            previous_event_sha256=None,
        )
        _, reused = _write_event(store, discovered)
        events.append(discovered)
        object_states.append(reused)
        current_state = "discovered"

        acquired = _event(
            attempt_id=attempt_id,
            sequence=2,
            occurred_at=request.retrieved_at,
            from_state="discovered",
            to_state="acquired",
            reason_code="SOURCE_ACQUIRED",
            evidence_refs=[
                f"media_sha256:{manifest.media_sha256}",
                f"transcript_sha256:{manifest.transcript_sha256}",
                f"segments:{len(manifest.segments)}",
            ],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, acquired)
        events.append(acquired)
        object_states.append(reused)
        current_state = "acquired"

        transcript_text = bundle.transcript_bytes.decode("utf-8-sig")
        secret_matches = _secret_matches(transcript_text)
        if secret_matches:
            raise IntakeFailure(
                "SECRET_LIKE_CONTENT",
                "safety_gate",
                "media transcript contains secret-like content",
                safe_context={
                    "patterns": secret_matches,
                    "observed_sha256": manifest.transcript_sha256,
                    "observed_bytes": manifest.transcript_byte_size,
                },
            )
        normalized = render_derivative(manifest)
        warnings = _prompt_findings(transcript_text)

        evidence = _evidence(
            attempt_id=attempt_id,
            source_id=source_id,
            bundle=bundle,
            failure=None,
        )
        evidence_bytes = _pretty_json_bytes(evidence)
        object_states.append(
            _put_immutable(store, evidence_key, evidence_bytes, content_type="application/json")
        )
        evidence_written = True

        media_raw_key, transcript_raw_key = _raw_keys(bundle)
        media_reused = _put_immutable(
            store,
            media_raw_key,
            bundle.media_bytes,
            content_type=manifest.media_type,
        )
        transcript_reused = _put_immutable(
            store,
            transcript_raw_key,
            bundle.transcript_bytes,
            content_type="text/markdown",
        )
        object_states.extend([media_reused, transcript_reused])
        artifacts.update(
            raw_blob_key=media_raw_key,
            raw_blob_reused=media_reused,
            transcript_raw_key=transcript_raw_key,
            transcript_raw_reused=transcript_reused,
        )

        acl_status = (
            "unresolved"
            if request.access_policy.policy_type == "unresolved"
            or request.access_policy.observation_source == "unresolved"
            else "resolved"
        )
        identity = {
            "schema_version": "intake-snapshot/v1",
            "source_id": source_id,
            "original_uri": canonical_locator,
            "connector_type": CONNECTOR_TYPE,
            "connector_version": CONNECTOR_VERSION,
            "retrieved_at": request.retrieved_at,
            "content_hash": manifest.media_sha256,
            "byte_size": manifest.media_byte_size,
            "mime_type": manifest.media_type,
            "encoding": "binary",
            "license": request.license.to_dict(),
            "owner": request.owner.to_dict(),
            "audience": request.audience,
            "access_policy": request.access_policy.to_dict(),
            "source_version": (
                f"media:{manifest.media_sha256}:{manifest.transcript_sha256}:"
                f"{manifest.manifest_sha256}:{manifest.transcription_tool}:"
                f"{manifest.transcription_model}:{manifest.transcription_version}"
            ),
            "parent_snapshot": request.parent_snapshot,
        }
        snapshot_id = snapshot_id_for(identity)
        snapshot_key = f"intake/v1/snapshots/{source_id}/{snapshot_id}/snapshot.json"
        snapshot = {
            **identity,
            "snapshot_id": snapshot_id,
            "acl_status": acl_status,
            "storage_location": _storage_location(
                store,
                media_raw_key,
                manifest.media_sha256,
            ),
        }
        snapshot_bytes = _pretty_json_bytes(snapshot)
        object_states.append(
            _put_immutable(store, snapshot_key, snapshot_bytes, content_type="application/json")
        )
        artifacts.update(snapshot_id=snapshot_id, snapshot_key=snapshot_key)

        snapshotted = _event(
            attempt_id=attempt_id,
            sequence=3,
            occurred_at=request.retrieved_at,
            from_state="acquired",
            to_state="snapshotted",
            reason_code="SNAPSHOT_WRITTEN",
            evidence_refs=[media_raw_key, transcript_raw_key, snapshot_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, snapshotted)
        events.append(snapshotted)
        object_states.append(reused)
        current_state = "snapshotted"

        normalized_hash = sha256_bytes(normalized)
        derivative_id = derivative_id_for(
            snapshot_id=snapshot_id,
            normalizer_id=NORMALIZER_ID,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content_hash=normalized_hash,
        )
        normalized_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/{normalized_hash}.md"
        )
        derivative_key = (
            f"intake/v1/normalized/{snapshot_id}/{NORMALIZER_ID}/"
            f"{NORMALIZER_VERSION}/derivative.json"
        )
        object_states.append(
            _put_immutable(store, normalized_key, normalized, content_type="text/markdown")
        )
        derivative = {
            "schema_version": "intake-derivative/v1",
            "derivative_id": derivative_id,
            "snapshot_id": snapshot_id,
            "normalizer_id": NORMALIZER_ID,
            "normalizer_version": NORMALIZER_VERSION,
            "normalized_content_hash": normalized_hash,
            "normalized_key": normalized_key,
            "byte_size": len(normalized),
            "mime_type": "text/markdown",
            "warnings": warnings,
            "media_evidence_key": evidence_key,
            "media_raw_key": media_raw_key,
            "transcript_raw_key": transcript_raw_key,
            "manifest_sha256": manifest.manifest_sha256,
            "language": manifest.language,
            "duration_ms": manifest.duration_ms,
            "segment_count": len(manifest.segments),
        }
        derivative_bytes = _pretty_json_bytes(derivative)
        object_states.append(
            _put_immutable(store, derivative_key, derivative_bytes, content_type="application/json")
        )
        artifacts.update(
            derivative_id=derivative_id,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
        )

        normalized_event = _event(
            attempt_id=attempt_id,
            sequence=4,
            occurred_at=request.retrieved_at,
            from_state="snapshotted",
            to_state="normalized",
            reason_code="DERIVATIVE_WRITTEN",
            evidence_refs=[normalized_key, derivative_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, normalized_event)
        events.append(normalized_event)
        object_states.append(reused)
        current_state = "normalized"

        if acl_status != "resolved" or request.owner.status != "resolved":
            raise IntakeFailure(
                "ACL_UNRESOLVED",
                "admission",
                "ACL or ownership is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )
        if request.license.status != "resolved":
            raise IntakeFailure(
                "LICENSE_UNRESOLVED",
                "admission",
                "license is unresolved",
                safe_context={"snapshot_id": snapshot_id},
            )

        accepted = _event(
            attempt_id=attempt_id,
            sequence=5,
            occurred_at=request.retrieved_at,
            from_state="normalized",
            to_state="accepted_for_compilation",
            reason_code="COMPILATION_ADMISSION_ACCEPTED",
            evidence_refs=[snapshot_key, derivative_key, evidence_key],
            previous_event_sha256=events[-1]["event_sha256"],
        )
        _, reused = _write_event(store, accepted)
        events.append(accepted)
        object_states.append(reused)

        result_key = f"intake/v1/attempts/{attempt_id}/result.json"
        result = IntakeResult(
            attempt_id=attempt_id,
            status="accepted_for_compilation",
            source_id=source_id,
            snapshot_id=snapshot_id,
            derivative_id=derivative_id,
            raw_blob_key=media_raw_key,
            snapshot_key=snapshot_key,
            normalized_key=normalized_key,
            derivative_key=derivative_key,
            result_key=result_key,
            rejection_key=None,
            idempotent=False,
            raw_blob_reused=media_reused,
            event_keys=_event_keys(attempt_id, events),
        )
        object_states.append(
            _put_immutable(
                store,
                result_key,
                _pretty_json_bytes(result.evidence_dict()),
                content_type="application/json",
            )
        )
        result = replace(result, idempotent=all(object_states))
        _write_output(output_dir, "media-acquisition.json", evidence_bytes)
        _write_output(output_dir, "snapshot.json", snapshot_bytes)
        _write_output(output_dir, "normalized.md", normalized)
        _write_output(output_dir, "derivative.json", derivative_bytes)
        _write_output(output_dir, "intake-result.json", _pretty_json_bytes(result.to_dict()))
        return result
    except IntakeFailure as failure:
        if not evidence_written and evidence_key and artifacts.get("source_id"):
            evidence = _evidence(
                attempt_id=attempt_id,
                source_id=str(artifacts["source_id"]),
                bundle=bundle,
                failure=failure,
            )
            object_states.append(
                _put_immutable(
                    store,
                    evidence_key,
                    _pretty_json_bytes(evidence),
                    content_type="application/json",
                )
            )
        return _reject(
            store=store,
            request=request,
            attempt_id=attempt_id,
            failure=failure,
            current_state=current_state,
            events=events,
            object_states=object_states,
            artifacts=artifacts,
            output_dir=output_dir,
        )
