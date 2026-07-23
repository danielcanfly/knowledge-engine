from __future__ import annotations

import os
from pathlib import Path

from .m25_review_surface import create_review_app, load_json

BATCH_PATH = Path(os.environ.get("M25_REVIEW_BATCH", "pilot/m25/m25-6-review-batch.json"))
LEDGER_PATH = Path(os.environ.get("M25_REVIEW_LEDGER", ".m25-review-ledger"))
app = create_review_app(
    load_json(BATCH_PATH),
    LEDGER_PATH,
    username=os.environ.get("M25_REVIEW_USERNAME", ""),
    password=os.environ.get("M25_REVIEW_PASSWORD", ""),
)
