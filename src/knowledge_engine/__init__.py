"""Knowledge Engine package."""

__version__ = "0.2.0"

# Install the production-general, product-first AQ semantic closure before callers
# import the owner-only runtime. The installer is idempotent and fail-closed:
# import-time errors should not mask ordinary package import failures elsewhere.
try:
    from . import m26_aq_final_recovery_runtime_guard as _final_recovery_runtime_guard
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

    _install_aq_semantic_patch()
    _install_aq_lifecycle_patch()
    _install_aq_surface_patch()
    _install_aq_universal_answerability_patch()
    _final_recovery_runtime_guard.apply()
    _install_aq_final_universal_recovery_patch()
except Exception:  # pragma: no cover - runtime modules expose concrete failures later
    pass
