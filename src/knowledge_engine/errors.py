class KnowledgeEngineError(RuntimeError):
    """Base deterministic Knowledge Engine failure."""


class ConfigurationError(KnowledgeEngineError):
    """Invalid environment or startup configuration."""


class IntegrityError(KnowledgeEngineError):
    """Release or artifact integrity verification failed."""


class AuthorizationError(KnowledgeEngineError):
    """Authentication or authorization failed."""


class ReleaseConflictError(KnowledgeEngineError):
    """Atomic channel update failed because the pointer changed."""
