from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .batch_spec import load_batch_spec
from .errors import IntegrityError
from .idempotent_replay_approval import validate_idempotent_replay_approval

_ALLOWED_CURRENT_STATES = {"production_promoted", "closed"}


def validate_historical_idempotent_replay_approval(
    *,
    approval_path: str | Path,
    spec_path: str | Path,
    request_path: str | Path,
    promotion_observation_path: str | Path,
    lifecycle_path: str | Path,
) -> dict[str, Any]:
    approval_source = Path(approval_path).resolve()
    spec_source = Path(spec_path).resolve()
    request_source = Path(request_path).resolve()
    promotion_source = Path(promotion_observation_path).resolve()
    lifecycle_source = Path(lifecycle_path).resolve()

    spec = load_batch_spec(spec_path)
    if spec.lifecycle_state not in _ALLOWED_CURRENT_STATES:
        raise IntegrityError(
            "historical replay approval requires current lifecycle state in "
            f"{sorted(_ALLOWED_CURRENT_STATES)!r}"
        )

    if spec.lifecycle_state == "production_promoted":
        result = validate_idempotent_replay_approval(
            approval_path=approval_path,
            spec_path=spec_path,
            request_path=request_path,
            promotion_observation_path=promotion_observation_path,
            lifecycle_path=lifecycle_path,
        )
    else:
        spec_payload = json.loads(spec_source.read_text(encoding="utf-8"))
        spec_payload["lifecycle_state"] = "production_promoted"

        lifecycle_payload = json.loads(
            lifecycle_source.read_text(encoding="utf-8")
        )
        transitions = lifecycle_payload.get("transitions")
        if not isinstance(transitions, list) or not transitions:
            raise IntegrityError("lifecycle history transitions are required")
        last = transitions[-1]
        if not isinstance(last, dict) or (
            last.get("from"),
            last.get("to"),
        ) != ("production_promoted", "closed"):
            raise IntegrityError(
                "closed lifecycle must end with production_promoted -> closed"
            )
        lifecycle_payload["transitions"] = transitions[:-1]
        lifecycle_payload["final_state"] = "production_promoted"
        lifecycle_payload["next_framework_action"] = (
            "run_idempotent_replay_and_close"
        )
        lifecycle_payload["next_legal_action"] = "review_idempotent_replay"
        lifecycle_payload.pop("replay_mutated_production", None)

        historical_spec = Path("governed_batches") / spec_source.name
        historical_approval = (
            Path("governed_batches/evidence") / approval_source.name
        )
        historical_promotion = (
            Path("governed_batches/evidence") / promotion_source.name
        )
        historical_lifecycle = (
            Path("governed_batches/evidence") / lifecycle_source.name
        )
        historical_request = Path("production_promotions") / request_source.name

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for path in (
                historical_spec,
                historical_approval,
                historical_promotion,
                historical_lifecycle,
                historical_request,
            ):
                (root / path).parent.mkdir(parents=True, exist_ok=True)

            (root / historical_spec).write_text(
                json.dumps(spec_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (root / historical_lifecycle).write_text(
                json.dumps(lifecycle_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (root / historical_approval).write_bytes(
                approval_source.read_bytes()
            )
            (root / historical_promotion).write_bytes(
                promotion_source.read_bytes()
            )
            (root / historical_request).write_bytes(request_source.read_bytes())

            original_directory = Path.cwd()
            try:
                os.chdir(root)
                result = validate_idempotent_replay_approval(
                    approval_path=historical_approval,
                    spec_path=historical_spec,
                    request_path=historical_request,
                    promotion_observation_path=historical_promotion,
                    lifecycle_path=historical_lifecycle,
                )
            finally:
                os.chdir(original_directory)

    result["lifecycle_state_at_approval"] = "production_promoted"
    result["current_lifecycle_state"] = spec.lifecycle_state
    result["approval_consumed"] = spec.lifecycle_state == "closed"
    return result
