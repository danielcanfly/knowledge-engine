"""Knowledge Engine package."""

import os

__version__ = "0.2.0"

# Install the production-general, product-first AQ semantic closure before callers
# import the owner-only runtime. The installer is idempotent and fail-closed:
# import-time errors should not mask ordinary package import failures elsewhere.
try:
    from .m26_aq_final_universal_recovery_patch import (
        install as _install_aq_final_universal_recovery_patch,
    )
    from .m26_aq_semantic_runtime_patch_v3 import install as _install_aq_semantic_patch
    from .m26_aq_semantic_runtime_patch_v3_lifecycle import (
        install as _install_aq_lifecycle_patch,
    )
    from .m26_aq_semantic_runtime_patch_v3_surface import (
        install as _install_aq_surface_patch,
    )
    from .m26_aq_universal_answerability_patch import (
        install as _install_aq_universal_answerability_patch,
    )
    from .m26_pa7_semantic_closure_runtime import (
        run_owner_arbitrary_query as _semantic_run_owner_arbitrary_query,
    )
    from . import m26_aq_final_recovery_runtime_guard as _final_recovery_runtime_guard

    _install_aq_semantic_patch()
    _install_aq_lifecycle_patch()
    _install_aq_surface_patch()
    _install_aq_universal_answerability_patch()
    _final_recovery_runtime_guard.apply()
    _install_aq_final_universal_recovery_patch()
    if os.environ.get("M26_QUERY_BUILD_SHA"):
        from . import m26_ask_api as _m26_ask_api

        _m26_ask_api.run_owner_arbitrary_query = _semantic_run_owner_arbitrary_query
        _m26_ask_api.RUNTIME_ENTRYPOINT = (
            "knowledge_engine.m26_pa7_semantic_closure_runtime.run_owner_arbitrary_query"
        )
except Exception:  # pragma: no cover - runtime modules expose concrete failures later
    pass
