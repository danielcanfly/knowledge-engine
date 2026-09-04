"""Knowledge Engine package."""

__version__ = "0.2.0"

# R3 successor: observability-only provider contract trace. The installer wraps
# fast-path normalization/response publication but never parser, validator, or retry policy.
from .m26_provider_contract_trace import install_runtime_trace as _install_m26_r3_runtime_trace

_install_m26_r3_runtime_trace()
del _install_m26_r3_runtime_trace
