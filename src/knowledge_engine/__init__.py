"""Knowledge Engine package."""

__version__ = "0.2.0"

# Install production-general AQ semantic closure compatibility before callers
# import the owner-only runtime.  The installer is idempotent and fail-closed:
# import-time errors should not mask ordinary package import failures elsewhere.
try:
    from .m26_aq_semantic_runtime_patch import install as _install_aq_semantic_patch

    _install_aq_semantic_patch()
except Exception:  # pragma: no cover - runtime modules expose concrete failures later
    pass
