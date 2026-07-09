from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from knowledge_engine.config import Settings
from knowledge_engine.m14_feedback import FeedbackIntake, feedback_object_keys
from knowledge_engine.m14_feedback_contracts import PublicFeedbackRequest
from knowledge_engine.storage import ObjectMetadata, ObjectStore, create_object_store


@dataclass
class PrefixStore:
    delegate: ObjectStore
    prefix: str

    def _key(self, key: str) -> str:
        return f"{self.prefix.rstrip('/')}/{key}"

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
        return self.delegate.put(
            self._key(key),
            data,
            content_type=content_type,
            sha256=sha256,
            expected_etag=expected_etag,
            only_if_absent=only_if_absent,
        )

    def get(self, key: str) -> bytes:
        return self.delegate.get(self._key(key))

    def head(self, key: str) -> ObjectMetadata | None:
        return self.delegate.head(self._key(key))

    def delete(self, key: str) -> None:
        self.delegate.delete(self._key(key))


def run(run_id: str) -> dict[str, object]:
    settings = Settings.from_env()
    delegate = create_object_store(settings)
    store = PrefixStore(delegate, f"canaries/m14-feedback/{run_id}")
    intake = FeedbackIntake(store, now=lambda: "2026-07-10T00:00:00Z")
    request = PublicFeedbackRequest(
        feedback_type="citation_issue",
        request_id="req_" + "1" * 32,
        release_id="r2-feedback-acceptance",
        audience="public",
        message="The citation should identify the exact supporting section.",
        citation_id="cite_" + "2" * 32,
        source_card_id="card_" + "3" * 32,
        concept_id="concepts/compiler",
        section_id="concepts/compiler#operations",
        reference_uri="https://example.com/spec?b=2&a=1",
        locale="en",
    )
    keys: tuple[str, str] | None = None
    try:
        accepted = intake.submit(
            request,
            client_key=f"r2-feedback-client:{run_id}",
            authenticated=False,
        )
        duplicate = intake.submit(
            request,
            client_key=f"r2-feedback-client:{run_id}",
            authenticated=False,
        )
        keys = feedback_object_keys(accepted.feedback_id)
        intake_record = json.loads(store.get(keys[0]))
        queue_record = json.loads(store.get(keys[1]))
        if accepted.status != "accepted":
            raise RuntimeError("first feedback submission was not accepted")
        if duplicate.status != "duplicate":
            raise RuntimeError("feedback replay was not detected as duplicate")
        if duplicate.feedback_id != accepted.feedback_id:
            raise RuntimeError("feedback replay identity changed")
        if intake_record.get("feedback_id") != accepted.feedback_id:
            raise RuntimeError("R2 intake feedback identity mismatch")
        if queue_record.get("feedback_id") != accepted.feedback_id:
            raise RuntimeError("R2 queue feedback identity mismatch")
        if queue_record.get("state") != "pending_review":
            raise RuntimeError("R2 feedback queue state mismatch")
        if queue_record.get("intake_sha256") != store.head(keys[0]).sha256:
            raise RuntimeError("R2 feedback queue intake hash mismatch")
        if intake_record["governance"]["source_write_allowed"] is not False:
            raise RuntimeError("R2 feedback intake widened Source permissions")
        if queue_record["production_write_allowed"] is not False:
            raise RuntimeError("R2 feedback queue widened production permissions")
        return {
            "status": "success",
            "feedback_id": accepted.feedback_id,
            "accepted_status": accepted.status,
            "replay_status": duplicate.status,
            "intake_sha256": store.head(keys[0]).sha256,
            "queue_sha256": store.head(keys[1]).sha256,
            "source_write_allowed": False,
            "production_write_allowed": False,
        }
    finally:
        if keys is not None:
            for key in reversed(keys):
                store.delete(key)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.run_id), sort_keys=True))


if __name__ == "__main__":
    main()
