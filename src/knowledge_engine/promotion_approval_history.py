from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .batch_spec import load_batch_spec
from .errors import IntegrityError
from .promotion_approval import validate_production_promotion_approval

_ALLOWED_CURRENT_STATES = {
    "request_spec_committed",
    "production_promoted",
    "closed",
}


def validate_historical_production_promotion_approval(
    *,
    approval_path: str | Path,
    spec_path: str | Path,
    request_path: str | Path,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    spec = load_batch_spec(spec_path)
    if spec.lifecycle_state not in _ALLOWED_CURRENT_STATES:
        raise IntegrityError(
            "historical promotion approval requires current lifecycle state in "
            f"{sorted(_ALLOWED_CURRENT_STATES)!r}"
        )

    if spec.lifecycle_state == "request_spec_committed":
        result = validate_production_promotion_approval(
            approval_path=approval_path,
            spec_path=spec_path,
            request_path=request_path,
        )
    else:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        payload["lifecycle_state"] = "request_spec_committed"
        with tempfile.TemporaryDirectory() as temporary_directory:
            historical_spec = Path(temporary_directory) / "historical-spec.json"
            historical_spec.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = validate_production_promotion_approval(
                approval_path=approval_path,
                spec_path=historical_spec,
                request_path=request_path,
            )

    result["lifecycle_state_at_approval"] = "request_spec_committed"
    result["current_lifecycle_state"] = spec.lifecycle_state
    result["approval_consumed"] = spec.lifecycle_state in {
        "production_promoted",
        "closed",
    }
    return result
