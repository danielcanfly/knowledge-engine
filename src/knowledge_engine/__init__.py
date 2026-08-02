"""Knowledge Engine package."""

__version__ = "0.2.0"

# Install production-general AQ semantic closure compatibility before callers
# import the owner-only runtime.  The installer is idempotent and fail-closed:
# import-time errors should not mask ordinary package import failures elsewhere.
try:
    from .m26_aq_semantic_runtime_patch import install as _install_aq_semantic_patch
    from .m26_pa7_semantic_closure_runtime import (
        run_owner_arbitrary_query as _semantic_run_owner_arbitrary_query,
    )

    _install_aq_semantic_patch()
    from . import m26_ask_api as _m26_ask_api

    _m26_ask_api.run_owner_arbitrary_query = _semantic_run_owner_arbitrary_query
    _m26_ask_api.RUNTIME_ENTRYPOINT = (
        "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
    )
except Exception:  # pragma: no cover - runtime modules expose concrete failures later
    pass
