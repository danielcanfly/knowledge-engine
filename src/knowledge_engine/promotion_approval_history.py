from __future__ import annotations

import json
import os
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
    approval_source = Path(approval_path).resolve()
    spec_source = Path(spec_path).resolve()
    request_source = Path(request_path).resolve()
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
        payload = json.loads(spec_source.read_text(encoding="utf-8"))
        payload["lifecycle_state"] = "request_spec_committed"

        historical_spec = Path("governed_batches") / spec_source.name
        historical_approval = (
            Path("governed_batches/evidence") / approval_source.name
        )
        historical_request = Path("production_promotions") / request_source.name

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / historical_spec).parent.mkdir(parents=True, exist_ok=True)
            (root / historical_approval).parent.mkdir(parents=True, exist_ok=True)
            (root / historical_request).parent.mkdir(parents=True, exist_ok=True)

            (root / historical_spec).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (root / historical_approval).write_bytes(approval_source.read_bytes())
            (root / historical_request).write_bytes(request_source.read_bytes())

            original_directory = Path.cwd()
            try:
                os.chdir(root)
                result = validate_production_promotion_approval(
                    approval_path=historical_approval,
                    spec_path=historical_spec,
                    request_path=historical_request,
                )
            finally:
                os.chdir(original_directory)

    result["lifecycle_state_at_approval"] = "request_spec_committed"
    result["current_lifecycle_state"] = spec.lifecycle_state
    result["approval_consumed"] = spec.lifecycle_state in {
        "production_promoted",
        "closed",
    }
    return result
