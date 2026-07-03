"""Compatibility facade for the canonical production release controller.

The production implementation lives in ``knowledge_engine.promotion``.
This module remains importable so older integrations do not select a second
controller implementation.
"""

from .promotion import (
    PromotionRequest,
    PromotionResult,
    RollbackResult,
    promote_release,
    rollback_release,
)

__all__ = [
    "PromotionRequest",
    "PromotionResult",
    "RollbackResult",
    "promote_release",
    "rollback_release",
]
