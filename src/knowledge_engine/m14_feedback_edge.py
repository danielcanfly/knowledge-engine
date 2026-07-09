from __future__ import annotations

from .m14_security import PUBLIC_API_PATHS, PUBLIC_PATHS, PUBLIC_POST_PATHS

FEEDBACK_PATH = "/v1/feedback"


def register_feedback_edge_path() -> None:
    PUBLIC_API_PATHS.add(FEEDBACK_PATH)
    PUBLIC_POST_PATHS.add(FEEDBACK_PATH)
    PUBLIC_PATHS.add(FEEDBACK_PATH)
